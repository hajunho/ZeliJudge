# 리눅스 KVM MMU 2차원 페이징(Two-Dimensional Paging) 및 확장 페이지 테이블(EPT) 엔진

## 문제 설명

현대 클라우드 인프라와 하이퍼바이저 가상화 환경(KVM, QEMU, Firecracker, AWS Nitro 등)에서 게스트 운영체제(Guest OS)는 자신이 물리 하드웨어 전체를 독점하고 있다고 가정하고 가상 메모리를 관리합니다. 초기 소프트웨어 가상화에서는 게스트 가상 주소($GVA$)를 호스트 물리 주소($HPA$)로 직접 매핑하기 위해 복잡하고 오버헤드가 큰 **섀도우 페이지 테이블(Shadow Page Table, SPT)** 기법을 사용했습니다.

하지만 현대 x86_64 프로세서(Intel VT-x, AMD-V)는 **하드웨어 지원 2차원 페이징(Two-Dimensional Paging, TDP)** 기술인 **Intel EPT (Extended Page Tables)** 및 **AMD NPT (Nested Page Tables)**를 지원합니다.
2차원 페이징 환경에서는 주소 변환이 2단계로 이루어집니다:
1. **1차원 변환 (게스트 내부)**: 게스트 가상 주소($GVA$) $\to$ 게스트 물리 주소($GPA$) (Guest CR3 레지스터 기반 게스트 4계층 페이지 테이블 순회)
2. **2차원 변환 (하이퍼바이저/하드웨어 MMU)**: 게스트 물리 주소($GPA$) $\to$ 실제 호스트 물리 주소($HPA$) (EPTP 레지스터 기반 EPT 4계층 페이지 테이블 순회)

하드웨어 MMU가 게스트 페이지 테이블 엔트리를 읽을 때 발생하는 모든 메모리 접근조차도 $GPA$이므로, 최악의 경우 한 번의 $GVA \to HPA$ 변환에 $(4+1) \times (4+1) - 1 = 24$번의 메모리 참조가 발생할 수 있습니다. 이를 효율적으로 제어하고 관리하기 위해 리눅스 커널 KVM의 MMU 서브시스템(`arch/x86/kvm/mmu/`)은 고도로 최적화된 TDP MMU 엔진을 운영합니다.

본 문제에서는 리눅스 커널 KVM의 **2차원 확장 페이지 테이블(EPT) MMU 엔진**을 정밀하게 구현해야 합니다. 엔진은 KVM 메모리 슬롯(`kvm_memslots`) 설정, 게스트 메모리 접근에 따른 EPT 워크 및 디맨드 페이징(Demand Paging), 빠른 페이지 폴트(Fast Page Fault) 기반 더티 로깅(Dirty Logging) 처리, 읽기 전용 슬롯 보호, 2MB 대용량 페이지(Hugepage) 할당, MMIO 영역 에뮬레이션 트랩, 그리고 슬롯 해제(`UNMAP_MEMSLOT`)에 따른 EPT 서브트리 재귀적 회수 및 `INVEPT` TLB 무효화를 완전하게 시뮬레이션해야 합니다.

---

## 시스템 아키텍처 및 2차원 페이징 구조

```
+---------------------------------------------------------------------------------------------------+
|                        Linux Kernel KVM x86 TDP MMU Architecture (EPT/NPT)                        |
+---------------------------------------------------------------------------------------------------+

   Guest Virtual Address (GVA)
              |
              | (Guest Page Walk: gCR3 -> gPML4 -> gPDP -> gPD -> gPT)
              v
   Guest Physical Address (GPA) [48-bit]
     +---------------+---------------+---------------+---------------+---------------+
     | Bits 47..39   | Bits 38..30   | Bits 29..21   | Bits 20..12   | Bits 11..0    |
     | PML4 Index    | PDP Index     | PD Index      | PT Index      | Page Offset   |
     +---------------+---------------+---------------+---------------+---------------+
              |
              | (Hardware MMU EPT Walk via EPTP / Fast Path)
              +-------------------------------------------------------------+
              |                                                             |
              v [EPT Hit]                                                   v [EPT Violation / Miss]
     +-------------------+                                         +-------------------------+
     |  Leaf SPTE Found  |                                         |   VM-Exit: EPT Fault    |
     +-------------------+                                         +-------------------------+
              |                                                                 |
              +---> Permissions OK? ---> [Direct Access -> HPA]                 |
              |                                                                 v
              +---> Write on WP Page?                              +-------------------------+
                         |                                         |  Lookup kvm_memslots    |
                         v                                         +-------------------------+
                [DIRTY_LOG_TRACKING?]                                  |                 |
                   |               |                                   v [Found]         v [Not Found]
                (Yes)             (No)                        +------------------+  +------------------+
                   |               |                          | Allocate Missing |  | MMIO Emulation   |
                   v               v                          | EPT Shadow Pages |  | (APIC / Devices) |
            +--------------+  +---------------+               +------------------+  +------------------+
            | Fast PF:     |  | PERM_DENIED / |                        |
            | Mark Bitmap, |  | Read-Only     |                        v
            | Upgrade SPTE |  | Protection    |               +------------------+
            +--------------+  +---------------+               | Map 4KB / 2MB    |
                                                              | Leaf SPTE to HPA |
                                                              +------------------+
```

---

## 2차원 EPT 페이징 수학적 명세 및 작동 규칙

### 1. 48비트 GPA 주소 분할 및 인덱싱
게스트 물리 주소 $GPA$ ($0 \le GPA < 2^{48}$)는 4단계의 9비트 인덱스와 12비트 오프셋으로 분해됩니다:
$$\text{idx}_4 = (GPA \gg 39) \land \text{0x1FF} \quad (\text{EPT PML4 인덱스})$$
$$\text{idx}_3 = (GPA \gg 30) \land \text{0x1FF} \quad (\text{EPT PDP 인덱스})$$
$$\text{idx}_2 = (GPA \gg 21) \land \text{0x1FF} \quad (\text{EPT PD 인덱스})$$
$$\text{idx}_1 = (GPA \gg 12) \land \text{0x1FF} \quad (\text{EPT PT 인덱스})$$
$$\text{offset} = GPA \land \text{0xFFF} \quad (\text{4KB 페이지 오프셋})$$

### 2. KVM 메모리 슬롯 (`kvm_memslots`)
하이퍼바이저는 호스트 가상 메모리 공간을 게스트 물리 주소 공간으로 매핑하는 메모리 슬롯 목록을 유지합니다.
각 슬롯은 `slot_id`, `base_gpa`, `size`, `base_hva`, `base_hpa`, 그리고 `flags` (`READONLY`, `DIRTY_LOG_TRACKING`)를 갖습니다:
- $GPA$가 어떤 슬롯에도 속하지 않는 경우 ($GPA < \text{base\_gpa}$ 또는 $GPA \ge \text{base\_gpa} + \text{size}$): 하드웨어 메모리가 아닌 장치 레지스터 접근이므로 **MMIO 에뮬레이션(`MMIO_EMULATION`)**으로 트랩됩니다.
- 유효한 슬롯에 속하는 경우, 해당 슬롯의 베이스 $HPA$를 기준으로 주소가 사상됩니다:
  $$HPA = \text{slot.base\_hpa} + (GPA - \text{slot.base\_gpa})$$

### 3. EPT 폴트 처리 및 디맨드 페이징 (Demand Paging)
1. **EPT 캐시 히트 (`HIT`)**:
   - EPT 트리를 탐색하여 리프 SPTE(Shadow Page Table Entry)가 존재하고 요구된 권한(`READ`, `WRITE`, `EXEC`)이 모두 충족되는 경우:
     - `accessed = True` 갱신.
     - `WRITE` 접근인 경우 `dirty = True` 갱신.
     - 성공적으로 사상된 $HPA$ 반환.
2. **권한 위반 및 빠른 페이지 폴트 (`FAST_PF_DIRTY_LOG`)**:
   - 리프 SPTE가 존재하나 `WRITE` 권한이 없는 상태에서 `WRITE` 접근이 발생한 경우:
     - 슬롯에 `READONLY` 플래그가 설정되어 있다면: 쓰기 불가 상태이므로 `PERM_DENIED_READONLY` 반환.
     - 슬롯에 `DIRTY_LOG_TRACKING` 플래그가 설정되어 있는 경우 (가상머신 실시간 마이그레이션 중):
       - 슬롯의 더티 비트맵에서 페이지 번호 $\text{page\_idx} = (GPA - \text{base\_gpa}) \gg 12$를 `True`로 마킹.
       - SPTE의 `write` 권한을 즉시 `True`로 승격하고 `dirty = True`, `accessed = True` 갱신.
       - 무거운 MMU 락 없이 처리되는 `FAST_PF_DIRTY_LOG` 이벤트 반환.
3. **EPT 누락에 따른 느린 페이지 폴트 (`PAGE_FAULT_RESOLVED`)**:
   - EPT 트리에 리프 엔트리가 없는 경우 (Not Present):
     - 슬롯이 존재하지 않으면 `MMIO_EMULATION` 반환.
     - 2MB 대용량 페이지 옵션(`hugepage=True`)이 활성화되어 있고 주소 및 슬롯 정렬 조건이 충족되면 Level 2(PD)에 2MB 리프 엔트리를 생성.
     - 그렇지 않으면 누락된 상위 중간 테이블(PML4 $\to$ PDP $\to$ PD)을 동적으로 할당하고 Level 1(PT)에 4KB 리프 엔트리를 생성.
     - 권한 설정: 슬롯이 `READONLY`이거나 `DIRTY_LOG_TRACKING` 활성 상태이면 기본 쓰기 권한을 차단(`write = False`)하여 이후 첫 쓰기 시점에 더티 트래킹을 수행하도록 설정.

### 4. 더티 로그 플러시 (`FLUSH_DIRTY_LOG`)
- 지정된 `slot_id`의 현재 더티 페이지 목록을 추출하여 반환하고 비트맵을 초기화합니다.
- 다음 라운드의 변경 사항을 감지하기 위해 해당 슬롯 범위에 매핑된 모든 EPT 리프 엔트리의 쓰기 권한을 제거(`write = False`, 쓰기 보호)하고 TLB를 무효화합니다.

### 5. 메모리 슬롯 해제 (`UNMAP_MEMSLOT`) 및 섀도우 페이지 회수
- 가상머신의 메모리 슬롯이 언맵될 때, 해당 슬롯에 속하는 모든 리프 SPTE를 무효화(Zap)합니다.
- 자식 엔트리가 모두 제거되어 비어 있는 중간 EPT 테이블(PT, PD, PDP)은 재귀적으로 메모리에서 해제(Free)하고 `INVEPT`를 수행합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "hugepage_support": true,
    "memslots": [
      {
        "slot_id": 0,
        "base_gpa": "0x0",
        "size": "0x40000000",
        "base_hva": "0x7f0000000000",
        "base_hpa": "0x100000000",
        "flags": []
      }
    ]
  },
  "operations": [
    {
      "op": "ACCESS",
      "gpa": "0x1000",
      "access_type": "READ",
      "hugepage": false
    },
    {
      "op": "INVEPT",
      "type": "SINGLE_CONTEXT"
    },
    {
      "op": "FLUSH_DIRTY_LOG",
      "slot_id": 2
    },
    {
      "op": "UNMAP_MEMSLOT",
      "slot_id": 1
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 연산 결과 리스트와 최종 MMU 상태 통계를 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "results": [
    {
      "status": "PAGE_FAULT_RESOLVED",
      "gpa": "0x1000",
      "hpa": "0x100001000",
      "level": 1,
      "is_huge": false,
      "write_perm": true,
      "tables_allocated": 3
    }
  ],
  "mmu_stats": {
    "ept_hits": 10,
    "ept_violations": 4,
    "fast_pf_count": 1,
    "slow_pf_count": 3,
    "mmio_count": 1,
    "invept_count": 1,
    "allocated_tables": 7,
    "freed_tables": 0,
    "active_tables": 7,
    "total_leaf_sptes": 3
  },
  "summary": {
    "memslot_count": 1,
    "status": "HEALTHY"
  }
}
```

---

## 제약 조건

- $0 \le \text{연산 수} \le 10,000$
- $1 \le \text{메모리 슬롯 수} \le 64$
- 주소 공간: 48비트 x86_64 물리 주소 체계 ($0 \le GPA < 2^{48}$)
- 지원 연산: `ACCESS`, `INVEPT`, `FLUSH_DIRTY_LOG`, `UNMAP_MEMSLOT`
- 표준 라이브러리만을 사용하여 외부 종속성 없이 동작해야 함
