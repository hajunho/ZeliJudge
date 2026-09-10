# Problem 291: 100개 가상머신을 띄웠더니 왜 메모리가 50GB나 중복 낭비돼요?!: 리눅스 커널 메모리 KSM(Kernel Samepage Merging `mm/ksm.c`): Stable Tree vs Unstable Tree, COW Break 쓰레싱(Thrashing), NUMA 노드 간 병합 지연 및 적응형 ksmd 스캔 튜너 (Linux Kernel Memory KSM: Stable/Unstable Tree Deduplication, CoW Break Thrashing & Adaptive ksmd Scan Rate)

## 문제 설명

대규모 IaaS 클라우드 데이터센터(OpenStack, KVM/QEMU, AWS Firecracker microVM)를 운영하는 인프라 가상화 엔지니어링 팀은 물리 호스트의 DRAM 메모리 병목 및 가상머신 밀집도(Consolidation Ratio) 한계로 인해 극심한 비용 위기에 직면했습니다.

단일 호스트 노드(128GB RAM)에 동일한 Ubuntu/CentOS Linux OS 이미지를 사용하는 수십~수백 대의 가상머신을 구동할 때, 각 VM이 적재하는 커널 텍스트, C 표준 라이브러리(`libc.so`), 파이썬/Go 런타임 및 정적 바이너리는 사실상 **100% 동일한 4KB 물리 메모리 페이지들로 중복 구성**되어 있습니다. 이로 인해 전체 메모리의 40~60% 이상이 아무런 가치 없이 중복 복제되어 물리 메모리가 조기 고갈되는 사태가 발생합니다.

리눅스 커널은 이를 해결하기 위해 커널 스레드 `ksmd`를 통해 프로세스/VM 메모리를 스캔하고 동일한 페이지를 하나의 쓰기 보호(Write-Protected Copy-on-Write) 페이지로 통합하는 **KSM(Kernel Samepage Merging, `mm/ksm.c`)** 서브시스템을 제공합니다.

그러나 KSM을 잘못 운영하면 다음과 같은 치명적인 성능 재앙이 발생합니다:
1. **CoW Break 쓰레싱 참사 (`COW_BREAK_THRASHING_CPU_SPIKE`)**:
   - 쓰기 작업이 빈번한 가변 힙(Heap) 메모리를 무리하게 KSM으로 병합하면, 쓰기 시도 즉시 하드웨어 페이지 폴트(`do_wp_page()`)가 폭발하고, 페이지를 다시 복제 분리(`CoW break`)하느라 CPU 코어가 100% 포화되며 메모리 절감 효과는 0으로 추락합니다.
2. **ksmd 스캔 기아 (`KSMD_SCAN_STARVATION`)**:
   - `pages_to_scan`이 너무 작거나 `sleep_millisecs`가 너무 길면, 가상머신의 메모리 할당 속도를 `ksmd`가 따라잡지 못해 중복 페이지의 80% 이상이 병합되지 못하고 방치됩니다.
3. **NUMA 노드 간 원격 메모리 지연 오염 (`CROSS_NUMA_MEMORY_LATENCY_SPIKE`)**:
   - `merge_across_nodes = 1`로 설정 시, NUMA Node 1의 VM 페이지가 Node 0의 물리 메모리로 통합되어 크로스 소켓 QPI/UPI 버스를 통한 원격 메모리 접근(Remote NUMA Latency, 70ns -> 150ns) 및 TLB Shootdown IPI 인터럽트 폭풍이 유발됩니다.

가상화 커널 엔지니어로서, 리눅스 커널 `mm/ksm.c`의 Stable Tree(안정 트리) 및 Unstable Tree(불안정 트리) 병합 상태 머신과 CoW Break 메커니즘을 시뮬레이션하고, 워크로드 특성에 맞춘 최적의 `sysfs` KSM 튜너를 구현하십시오.

---

## 핵심 시스템 파라미터 및 원리

### 1. KSM 트리 아키텍처 (`mm/ksm.c`)
- **`stable_tree` (안정 트리)**:
  - 이미 병합되어 쓰기 금지(Write-Protected, CoW)된 정규 KSM 물리 페이지들을 관리하는 레드-블랙 트리(RB-Tree).
  - 새로운 후보 페이지가 Stable Tree의 기존 KSM 페이지와 내용(Checksum/Hash)이 일치하면, 즉시 해당 KSM 페이지를 가리키도록 페이지 테이블 엔트리(PTE)를 갱신하고 기존 페이지를 해제하여 `pages_sharing`을 증가시킵니다.
- **`unstable_tree` (불안정 트리)**:
  - 현재 스캔 패스에서 처음 발견된 미병합 후보 페이지들을 임시 보관하는 RB-Tree.
  - 이전에 등록된 후보 페이지와 동일한 내용이 다시 발견되면, 두 페이지를 하나의 새로운 KSM 정규 페이지로 묶어 `stable_tree`로 승격(`pages_shared++`, `pages_sharing++`)합니다.
  - **불안정 트리의 주기적 무효화**: 불안정 트리에 보관된 페이지는 쓰기 금지 상태가 아니므로 내용이 언제든 변경될 수 있습니다. 따라서 매 스캔 패스(`scan_pass`) 시작 시 불안정 트리는 100% 완전히 초기화(Clear)됩니다.

---

### 2. KSM 메트릭 및 제어 인터페이스
- `total_mergeable_pages`: `MADV_MERGEABLE` 플래그가 설정된 총 후보 페이지 수
- `pages_shared`: Stable Tree에 등록된 고유한 KSM 물리 페이지 수
- `pages_sharing`: 중복 제거되어 실제로 절약된 가상 메모리 페이지 수
- `pages_unshared`: 병합되지 못하고 단독으로 남아 있는 페이지 수
- `cow_breaks`: 쓰기 시도로 인해 공유가 깨지고 독립 페이지로 분리된 횟수
- `memory_saved_mb`: $\text{pages\_sharing} \times 4096 / (1024 \times 1024)$
- `dedup_ratio`: $\text{pages\_sharing} / \text{total\_mergeable\_pages}$

---

## 입력 형식 (`sys.stdin`)

JSON 객체로 주어지며 `mode`에 따라 동작합니다:

### 모드 1: `SIMULATE_KSM`
```json
{
  "mode": "SIMULATE_KSM",
  "ksmd_config": {
    "pages_to_scan": 100,
    "sleep_millisecs": 20,
    "merge_across_nodes": false,
    "max_page_sharing": 256
  },
  "scan_passes": 3,
  "vms": [
    {
      "vm_id": "VM_01",
      "numa_node": 0,
      "pages": [
        {
          "page_id": "P_01",
          "content_hash": "OS_KERNEL_TEXT",
          "write_frequency": 0.0,
          "is_mergeable": true
        }
      ]
    }
  ]
}
```

### 모드 2: `ADAPTIVE_KSM_TUNER`
```json
{
  "mode": "ADAPTIVE_KSM_TUNER",
  "system_profile": {
    "target_workload_type": "WRITE_INTENSIVE_DATABASE",
    "numa_nodes_count": 2,
    "total_host_memory_gb": 128,
    "active_vms_count": 16
  }
}
```

---

## 출력 형식 (`sys.stdout`)

단일 행의 압축된 JSON 문자열을 출력합니다.
