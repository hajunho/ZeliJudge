# 리눅스 커널 KVM EPT 2차원 페이징 위반 처리 및 더티 페이지 로깅 엔진 (Linux Kernel KVM EPT MMU Paging Engine)

## 문제 설명

클라우드 하이퍼바이저(KVM, AWS Nitro, Google Cloud Compute Engine)가 가상머신(Guest VM)을 실행할 때, 게스트 OS가 인식하는 물리 메모리(Guest Physical Address, GPA)를 호스트 하이퍼바이저의 실제 물리 메모리(Host Physical Address, HPA)로 투명하게 변환해 주는 x86 하드웨어 가상화 기술이 바로 **Intel EPT (Extended Page Tables) / AMD NPT (Nested Page Tables)** 기반의 **2차원 페이징(Two-Dimensional Paging, 2DP)** 서브시스템(`arch/x86/kvm/mmu/mmu.c`, `arch/x86/kvm/vmx/vmx.c`)입니다.

```
+---------------------------------------------------------------------------------+
|                       KVM 2차원 페이징 (Two-Dimensional Paging)                 |
+---------------------------------------------------------------------------------+
| [Dimension 1: Guest Virtual Address (GVA)]  ---> [Guest Physical Address (GPA)] |
| (Managed by Guest OS Kernel: CR3 Page Table Walk)                               |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
| [Dimension 2: Guest Physical Address (GPA)] ---> [Host Physical Address (HPA)]  |
| (Managed by KVM Hypervisor: EPTP 4-Level Radix Table PML4 -> PDPT -> PD -> PT)  |
+---------------------------------------------------------------------------------+
                                         |
            [ EPT Violation 발생: EXIT_REASON_EPT_VIOLATION ]
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |  KVM MMU Page Fault Handler (kvm_mmu_page_fault / direct_page_fault)      |
   +---------------------------------------------------------------------------+
          |                                                    |
          v (Fast Path: 쓰기 보호 위반)                        v (Slow Path: 미매핑)
+------------------------------------+               +----------------------------+
| 더티 페이지 로깅 (Dirty Logging)   |               | memslot 검색 및 EPT 구축   |
| - GFN을 dirty_bitmap에 즉시 기록   |               | - 슬롯 부재 시: MMIO 디스패치|
| - 쓰기 권한 복구 (w = True)        |               | - 2MB 정렬 시: 휴지 페이지 결합|
| - VM 즉시 재개 (FAST_DIRTY_LOGGED) |               | - 4KB 기본 페이지 매핑     |
+------------------------------------+               +----------------------------+
```

### 1. 2대 경로 및 상태 전이 명세

#### 1.1 Fast Path: 라이브 마이그레이션 더티 페이지 로깅
가상머신 무중단 이전(Live Migration) 시 KVM은 메모리 슬롯에 `dirty_logging = True`를 활성화하고, 기존의 모든 EPT 리프 엔트리의 쓰기 권한(`w = False`)을 박탈합니다:
- 게스트가 쓰기(`WRITE`)를 시도하면 즉시 `EXIT_REASON_EPT_VIOLATION`이 발생합니다.
- KVM은 복잡한 전체 페이지 테이블 워크를 거치지 않고, 캐시된 슬롯의 `dirty_bitmap`에 해당 GFN을 등록한 뒤 쓰기 권한(`w = True`, `dirty = True`)을 복원하여 마이크로초 단위로 복귀합니다 (`FAST_DIRTY_LOGGED`).

#### 1.2 Slow Path: 메모리 슬롯 탐색 및 EPT 매핑
- **MMIO 에뮬레이션**:
  GPA에 대응하는 `memslot`이 존재하지 않는 경우, PCI BAR나 APIC 등의 하드웨어 메모리 맵 I/O 영역 접근으로 판단하여 게스트 탈출(`MMIO_EMULATION`)을 반환합니다.
- **휴지 페이지(Huge Page) 결합**:
  슬롯이 휴지 페이지를 지원하고, GFN과 HFN이 모두 2MB 경계(512 프레임 단위)에 정렬되어 있으며 슬롯 크기가 512페이지 이상인 경우, 레벨 2 EPT에 2MB 휴지 페이지(`huge_page = True`)를 직접 결합하여 TLB 오버헤드를 극소화합니다.

#### 1.3 하드웨어 TLB 무효화 (`INVEPT`)
EPT 테이블 변경 시 `invept` 명령을 통해 호스트 CPU의 EPT TLB 엔트리를 무효화합니다.

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "memslots": [
      {
        "slot_id": 0,
        "base_gfn": 0,
        "npages": 1024,
        "base_hfn": 131072,
        "supports_huge_pages": true
      }
    ]
  },
  "operations": [
    {"op": "ACCESS_GPA", "vcpu_id": 0, "gpa": 0, "access_type": "READ"},
    {"op": "ACCESS_GPA", "vcpu_id": 0, "gpa": 0, "access_type": "WRITE"},
    {"op": "ENABLE_DIRTY_LOGGING", "slot_id": 0},
    {"op": "ACCESS_GPA", "vcpu_id": 0, "gpa": 0, "access_type": "WRITE"},
    {"op": "GET_DIRTY_BITMAP", "slot_id": 0}
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "stats": {
    "ept_violations": 2,
    "fast_dirty_logged": 1,
    "slow_path_mapped": 1,
    "huge_pages_mapped": 1,
    "mmio_exits": 0,
    "tlb_invept_count": 0
  },
  "ept_table": {
    "0": {
      "hfn": 131072,
      "r": true,
      "w": false,
      "x": true,
      "huge_page": true,
      "dirty": true
    }
  },
  "dirty_bitmaps": {
    "0": [0]
  },
  "history": [...],
  "event_log": [...]
}
```
