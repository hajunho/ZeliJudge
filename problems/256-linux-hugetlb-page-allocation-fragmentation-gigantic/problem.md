# #256 [DB를 재시작했을 뿐인데 왜 메모리가 부족하다며 부팅이 안 돼요?!: 리눅스 커널 HugeTLB/hugetlbfs 정적 풀 할당, Buddy Allocator Order-9 연속성 단편화 실패와 1GB Gigantic Page 부팅 예약 vs 호스트 OOM 고갈 (Linux Kernel Memory: HugeTLB / hugetlbfs Static Pool Allocation, Buddy Allocator Order-9 Contiguity Failure, 1GB Gigantic Page Boot Reservation & Host Memory Starvation)]

## 1. 장애 및 실무 시나리오

국내 최대 규모의 온라인 결제 플랫폼 데이터베이스 운영팀은 수십 테라바이트의 트랜잭션을 처리하는 메인 PostgreSQL 15 및 Oracle 19c 고성능 DB 인프라를 운영하고 있습니다.

데이터베이스 버퍼 풀(PostgreSQL의 `shared_buffers`, Oracle의 `SGA`)이 수십 기가바이트에 달할 때 표준 4KB 페이징을 사용하면 다음과 같은 심각한 성능 저하가 발생합니다:
- **TLB(Translation Lookaside Buffer) 미스 폭증**: CPU의 L1/L2 TLB 캐시 항목 수는 수천 개에 불과하므로, 64GB 버퍼 풀을 4KB 페이지(1,677만 개)로 관리하면 무작위 메모리 접근 시 거의 매번 TLB 미스가 발생하여 4단계 페이지 테이블 워크(Page Table Walk)에 수십~수백 나노초의 지연이 누적됩니다.
- **페이지 테이블 메모리 오버헤드**: 연결된 클라이언트 커넥션마다 수백 메가바이트~수 기가바이트의 페이지 테이블이 복제 할당되어 OS 메모리가 낭비됩니다.

이를 극복하기 위해 DBA는 2MB 단위의 대용량 페이지인 **HugeTLB (hugetlbfs)**를 도입하여 `huge_pages = on`으로 설정하고 서비스를 성공적으로 오픈했습니다.

```
[4KB 페이징 (표준 메모리)]
  가상 주소 -> PML4 -> PDP -> PD -> PT -> 4KB 물리 메모리 (4단계 워크, TLB 미스 빈번)
  (64GB RAM = 16,777,216개 페이지 테이블 엔트리 필요, 막대한 메모리 낭비)

[2MB HugeTLB (hugetlbfs)]
  가상 주소 -> PML4 -> PDP -> PD (Huge Page 플래그) -> 2MB 연속 물리 메모리 (3단계 단축)
  (64GB RAM = 단 32,768개 엔트리, TLB 커버리지 512배 확장, TLB 미스 99% 제거!)

[1GB Gigantic Page (부팅 예약 전용)]
  가상 주소 -> PML4 -> PDP (Gigantic 플래그) -> 1GB 연속 물리 메모리 (2단계 단축)
  (64GB RAM = 단 64개 엔트리, 극단적 초저지연 KVM 가상화 / DPDK 전용)
```

그러나 서버 가동 45일째 되던 날, 마이너 보안 패치를 위해 새벽 점검 중 PostgreSQL을 재시작하자 다음과 같은 **치명적인 서비스 기동 불가(FATAL Crash)**가 발생했습니다:

```
2026-09-10 03:00:15 KST [12345] FATAL: could not map anonymous shared memory: Cannot allocate memory
2026-09-10 03:00:15 KST [12345] HINT: This error usually means that PostgreSQL's request for a shared memory
segment exceeded available HugePages. Set the parameter "huge_pages = try" or adjust /proc/sys/vm/nr_hugepages.
2026-09-10 03:00:15 KST [12345] LOG: database system is shut down
```

당직 DBA는 원인을 파악하기 위해 시스템 상태를 점검했으나, 기이한 현상들이 연쇄적으로 보고되었습니다:
1. **버디 할당자(Buddy Allocator) Order-9 연속성 단편화**:
   - `free -m` 명령어로 확인했을 때 가용 메모리가 25GB나 남아있었습니다!
   - 이에 DBA가 `echo 14000 > /proc/sys/vm/nr_hugepages`로 동적 풀 확장을 시도했으나, 2MB 대형 페이지는 **물리적으로 연속된 512개의 4KB 페이지(Order-9 = $2^9 \times 4\text{KB} = 2048\text{KB}$)**를 필요로 합니다.
   - 45일간의 파일 I/O와 메모리 할당/해제로 인해 물리 메모리가 심하게 조각나(외부 단편화, External Fragmentation), 커널이 연속된 Order-9 블록을 찾지 못해 요청량의 극히 일부만 할당하고 실패했습니다.
2. **1GB Gigantic Page 런타임 동적 할당 불가**:
   - 일부 엔지니어가 1GB 페이지로 전환하려고 `echo 16 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages`를 시도했으나 즉시 거부되었습니다. 1GB 페이지(Order-18)는 부팅 시점(`default_hugepagesz=1G hugepagesz=1G`)에 예약하지 않으면 런타임에는 사실상 할당이 불가능합니다.
3. **HugeTLB 정적 풀 과다 예약과 호스트 OOM Killer 사살 참사**:
   - 또 다른 노드에서는 여유를 둔다며 64GB 서버에 HugeTLB를 60GB(30,000개)나 정적 예약해 두었습니다.
   - HugeTLB 풀로 예약된 메모리는 커널의 `hugetlb_pool`에 영구 고정(Pinned/Locked)되어, 페이지 캐시나 kswapd 스왑, 일반 프로세스가 **단 1바이트도 꺼내 쓸 수 없습니다**.
   - 결과적으로 DB 외의 SSH 데몬, 모니터링 에이전트, 백업 스크립트가 쓸 일반 RAM이 512MB 이하로 고갈되어, 30GB의 HugeTLB가 텅텅 비어있음에도 불구하고 리눅스 OOM Killer가 발동하여 호스트 프로세스들을 무차별 사살했습니다.
4. **`vm.hugetlb_shm_group` 권한 불일치**:
   - POSIX 공유 메모리(`shmget(SHM_HUGETLB)`) 사용 시 프로세스의 GID가 커널 파라미터 `vm.hugetlb_shm_group`과 일치하지 않아 `EPERM` 권한 거부로 기동이 실패했습니다.

당신은 인프라 커널/DB 플랫폼 아키텍트로서, 부팅 예약, 런타임 동적 확장, 버디 할당자 단편화 검증, 공유 메모리 권한, PostgreSQL `huge_pages` 옵션(`on`, `try`, `off`) 및 호스트 OOM 위험을 정밀 판정하는 시뮬레이터를 구현해야 합니다.

---

## 2. 시스템 아키텍처 및 상태 전이도

```
  +========================================================================+
  |              물리 RAM (예: 64GB = 65,536 MB, NUMA 노드 분할)             |
  +========================================================================+
         |                                                 |
         v (부팅 시 영구 잠금 / GRUB Boot Parameter)           v (일반 OS 가용 메모리)
  +-------------------------------------+         +------------------------+
  |        HugeTLB Locked Pool          |         |     Normal RAM Pool    |
  |  - 2MB Pool (hugepages_2m_boot)     |         |  - OS 커널 코드 & 버퍼   |
  |  - 1GB Pool (hugepages_1g_boot)     |         |  - Page Cache (파일 I/O) |
  |  * kswapd 회수 불가 (Non-reclaimable)|         |  - 일반 Heap / Stack   |
  +-------------------------------------+         +------------------------+
         |                                                 |
         | [1] 프로세스 공유 메모리 할당                          | [2] 4KB Fallback
         |     (mmap / shmget)                             |     (huge_pages=try)
         v                                                 v
  +-------------------------------------+         +------------------------+
  |    PostgreSQL / Oracle / KVM        |         |  4KB Paging TLB Miss   |
  |    Shared Buffers (2MB / 1GB)       |         |  성능 저하 및 메모리 소비  |
  +-------------------------------------+         +------------------------+
         ^
         | [3] 런타임 동적 풀 확장 (/proc/sys/vm/nr_hugepages)
         |     - 1GB: 런타임 할당 영구 금지 (Order-18 Contiguity)
         |     - 2MB: Buddy Allocator Order-9 연속 블록 탐색
         |       (외부 단편화 발생 시 일부만 할당되고 실패!)
  +-------------------------------------+
  |   Buddy Allocator (Order 0 ~ 10)    |
  |   Order 9 (2MB) Free Blocks Check   |
  +-------------------------------------+
```

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다:

```json
{
  "system_hardware": {
    "total_ram_mb": 65536,
    "numa_nodes": 2,
    "ram_per_node_mb": 32768,
    "page_size_kb": 4
  },
  "kernel_boot_params": {
    "default_hugepagesz": "2M",
    "hugepages_2m_boot": 16384,
    "hugepages_1g_boot": 0
  },
  "runtime_state": {
    "sysctl_nr_hugepages_2m": 16384,
    "hugetlb_shm_group": 1001,
    "normal_memory_used_mb": 20000,
    "buddy_allocator_state": {
      "node_0": {
        "order_9_free_blocks": 500,
        "fragmentation_index": 0.85
      },
      "node_1": {
        "order_9_free_blocks": 400,
        "fragmentation_index": 0.88
      }
    }
  },
  "workload_requests": [
    {
      "request_id": "req-1",
      "action": "PROCESS_ALLOCATION",
      "process_name": "postgres",
      "process_gid": 1001,
      "page_size_requested": "2M",
      "hugepages_requested": 12000,
      "allocation_type": "MMAP_HUGETLB",
      "huge_pages_setting": "on"
    }
  ]
}
```

### 파라미터 제약조건:
- `total_ram_mb`: 전체 물리 RAM 크기 ($16384 \le M \le 524288$).
- `hugepages_2m_boot`: 부팅 시 예약된 2MB 대형 페이지 수 (페이지당 2MB).
- `hugepages_1g_boot`: 부팅 시 예약된 1GB 거대 페이지 수 (페이지당 1024MB).
- `hugetlb_shm_group`: SysV IPC 공유 메모리(`SHM_HUGETLB`) 허용 GID (0은 root).
- `buddy_allocator_state`: 각 NUMA 노드별 남은 Order-9 연속 블록 수.
- `workload_requests`: 수행할 작업 요청 리스트:
  - `action == "SYSCTL_EXPAND_HUGEPAGES"`:
    - `target_page_size`: `"2M"` 또는 `"1G"`.
    - `requested_total_hugepages`: 설정하고자 하는 총 페이지 수.
  - `action == "PROCESS_ALLOCATION"`:
    - `process_name`: 프로세스 이름 문자열.
    - `process_gid`: 프로세스 실행 GID.
    - `page_size_requested`: `"2M"` 또는 `"1G"`.
    - `hugepages_requested`: 요청 페이지 수.
    - `allocation_type`: `"MMAP_HUGETLB"` (익명 mmap) 또는 `"SHM_HUGETLB"` (POSIX/SysV 공유 메모리).
    - `huge_pages_setting`: `"on"` (엄격), `"try"` (4KB 폴백 허용), `"off"`.

---

## 4. 시뮬레이션 규칙 및 상태 판정 계층

### 1단계: 부팅 및 정적 풀 초기화
- 부팅 시 예약된 HugeTLB 크기: `hugetlb_reserved_mb = pool_2m_total * 2 + pool_1g_total * 1024`.
- 일반 가용 RAM: `free_normal_ram_mb = total_ram_mb - hugetlb_reserved_mb - normal_memory_used_mb`.

### 2단계: 워크로드 요청 처리
1. **동적 풀 확장 (`SYSCTL_EXPAND_HUGEPAGES`)**:
   - `target_page_size == "1G"`:
     - 1GB Gigantic Page는 런타임 동적 할당 불가 $\rightarrow$ 즉시 `status = "GIGANTIC_1G_BOOT_RESERVATION_REQUIRED"` 중단.
   - `target_page_size == "2M"`:
     - 추가 필요량 $\Delta = \text{requested\_total} - \text{pool\_2m\_total}$.
     - $\Delta > 0$일 때, 버디 할당자의 전체 Order-9 가용 블록 합계 및 남은 일반 RAM 용량과 비교.
     - 가용 Order-9 블록이 $\Delta$보다 작으면: 실제 할당량만 반영 후 `status = "FRAGMENTATION_ORDER9_CONTIGUITY_FAILURE"` 중단.
     - 가용 블록이 충분하면: 풀 확장 성공, Order-9 블록 차감, 일반 RAM 차감.
2. **프로세스 공유 메모리 할당 (`PROCESS_ALLOCATION`)**:
   - `allocation_type == "SHM_HUGETLB"`인 경우: `process_gid != 0`이고 `process_gid != hugetlb_shm_group`이면 `status = "PERMISSION_DENIED_SHM_GROUP"` 중단.
   - 요청 페이지 크기(1G / 2M)에 해당하는 풀의 가용 페이지 수(`pool_free = pool_total - pool_allocated`) 확인.
   - 여유 페이지가 충분하면: 즉시 할당 성공 (`pool_allocated += requested`).
   - 여유 페이지가 부족한 경우:
     - `huge_pages_setting == "on"`이면: `status = "FATAL_HUGETLB_POOL_EXHAUSTED"` 중단.
     - `huge_pages_setting == "try"`이면: 4KB 일반 RAM으로 폴백.
       - 남은 일반 RAM(`free_normal_ram_mb`)이 부족하면 `status = "HOST_OOM_DUE_TO_HUGETLB_OVERRESERVATION"` 중단.
       - 일반 RAM이 충분하면 `status = "DEGRADED_4KB_PAGING_FALLBACK"` 경고 기록.

### 3단계: 호스트 메모리 기아(OOM) 최종 검증
- 모든 요청 완료 후, HugeTLB 풀 잠금으로 인해 남은 일반 RAM이 안전 임계치(512MB) 미만으로 떨어지면:
  - HugeTLB에 미할당된 빈 페이지가 남아있더라도 커널/호스트 프로세스에 할당할 수 없어 OOM Killer가 발동하므로 `status = "HOST_OOM_DUE_TO_HUGETLB_OVERRESERVATION"`으로 판정.
- 모든 과정이 정상이고 문제 없으면 `status = "OPTIMAL_HUGETLB_LINE_PERFORMANCE"`.

---

## 5. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "OPTIMAL_HUGETLB_LINE_PERFORMANCE",
  "metrics": {
    "total_ram_mb": 65536,
    "hugetlb_pool_2m_total": 16384,
    "hugetlb_pool_2m_free": 4384,
    "hugetlb_pool_1g_total": 0,
    "hugetlb_pool_1g_free": 0,
    "hugetlb_total_reserved_mb": 32768,
    "normal_ram_free_mb": 16768,
    "normal_ram_used_mb": 16000,
    "remaining_order_9_blocks": 2300
  },
  "diagnostics": [
    "[c1-req-pg] postgres allocated 12000 2MB huge pages."
  ],
  "recommended_tuning": {
    "suggestion": "Optimal HugeTLB configuration maintained."
  }
}
```
