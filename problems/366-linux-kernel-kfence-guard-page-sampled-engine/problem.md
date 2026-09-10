# Linux Kernel KFENCE (Kernel Electric-Fence) 가드 페이지 샘플링 및 OOB / UAF 저오버헤드 탐지 엔진

## 문제 설명

리눅스 커널의 **KFENCE(Kernel Electric-Fence / `mm/kfence/core.c`, `include/linux/kfence.h`)**는 Linux 5.12에 도입된 **실운영(Production) 환경 전용** 메모리 안전성(Memory Safety) 탐지 서브시스템입니다.

기존의 KASAN(Kernel Address Sanitizer)은 메모리 접근을 바이트 단위로 완벽히 검사하지만, CPU 속도가 2배 저하되고 메모리 사용량이 20% 이상 증가하여 개발/테스트 환경에서만 사용할 수 있습니다. 반면 **KFENCE**는 1% 미만의 극소 오버헤드로 운영 환경에서 발생하는 OOB(Out-of-Bounds Buffer Overflow/Underflow)와 UAF(Use-After-Free), Double-Free를 실시간으로 탐지합니다.

```
 [KFENCE 메모리 풀 구조: 2 * num_slots + 1 페이지]
 +------------+------------+------------+------------+------------+
 | Guard Pg 0 | Obj Slot 0 | Guard Pg 1 | Obj Slot 1 | Guard Pg 2 | ...
 | (Unmapped) |  (4096 B)  | (Unmapped) |  (4096 B)  | (Unmapped) |
 +------------+------------+------------+------------+------------+
                     |
                     +---> 우측 정렬 (align_right=true):
                           [ Slack Space ][ Object Payload ] | (Guard Page 1: #PF 즉시 발생!)
```

### 핵심 아키텍처 및 동작 원리
1. **샘플링 기반 할당 (Sampled Allocation)**:
   - 모든 커널 슬랩 할당 중 $K$번째 요청(`alloc_counter % sample_interval == 0`)만을 무작위/주기적으로 가로채어 KFENCE 전용 풀에 할당합니다.
   - 샘플링되지 않은 나머지 할당이나, KFENCE 풀이 가득 찬(`pool_full_fallbacks`) 경우에는 기존 SLUB 할당기로 정상 처리합니다.
2. **가드 페이지(Guard Page)와 하드웨어 MMU 페이지 폴트(#PF)**:
   - KFENCE 풀의 각 객체 페이지 양쪽에는 매핑되지 않은(Unmapped / PTE 보호) 가드 페이지가 배치됩니다.
   - 객체는 페이지의 왼쪽 끝(`align_right=false`, 언더플로우 감지) 또는 오른쪽 끝(`align_right=true`, 오버플로우 감지)에 밀착 배치됩니다.
   - 객체 경계를 1바이트라도 벗어나 인접 가드 페이지에 접근하면 CPU 하드웨어 MMU가 즉각 페이지 폴트(`CRASH_OOB_GUARD_PAGE`)를 발생시킵니다.
3. **Use-After-Free (UAF) 방어**:
   - 객체가 `kfree()`되면, 해당 객체가 속한 페이지 전체를 즉시 미매핑(`PROT_NONE`) 상태로 전환합니다.
   - 이후 댕글링 포인터로 해당 페이지에 접근하면 즉각 페이지 폴트(`CRASH_USE_AFTER_FREE`)가 발생합니다.
4. **이중 해제 (Double Free) 감지**:
   - 이미 `FREED` 상태인 슬롯에 대해 다시 `kfree()`가 호출되면 커널 버그 리포트(`BUG_KFENCE_DOUBLE_FREE`)를 생성합니다.

본 문제에서는 KFENCE 풀의 가드 페이지 레이아웃, 샘플링 메커니즘, 좌우 정렬 오프셋 계산, 메모리 접근 하드웨어 페이지 폴트 에뮬레이션 및 슬롯 재활용 상태 머신을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "page_size": 64,
  "num_slots": 2,
  "sample_interval": 2,
  "operations": [
    {
      "op": "KMALLOC",
      "size": 32,
      "align_right": true,
      "backtrace": "net_buf"
    },
    {
      "op": "KMALLOC",
      "size": 40,
      "align_right": true,
      "backtrace": "fs_inode"
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 4184,
      "size": 40,
      "is_write": false
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 4224,
      "size": 4,
      "is_write": false
    }
  ]
}
```

### 파라미터 규격
- `page_size` (정수, 기본 64): 시뮬레이션 페이지 크기 (바이트 단위, 항상 8의 배수).
- `num_slots` (정수, 기본 4): KFENCE 풀이 보유한 객체 슬롯 개수. 전체 풀 크기는 `(2 * num_slots + 1) * page_size`이며, 시작 주소는 `4096`입니다.
  - 가드 페이지 인덱스: `pool_base + (2 * i) * page_size` ($0 \le i \le \text{num\_slots}$)
  - 객체 슬롯 $i$의 페이지 주소: `pool_base + (2 * i + 1) * page_size` ($0 \le i < \text{num\_slots}$)
- `sample_interval` (정수, 기본 2): 샘플링 간격 ($K$). $K$의 배수 번째 할당 요청이 KFENCE 풀로 라우팅됩니다.
- `operations` (배열): 순차적으로 실행할 연산 목록.
  - `KMALLOC`:
    - `size`: 요청 바이트 크기 (정수).
    - `align_right`: 우측 가드 밀착 여부 (불리언, 기본 `true`).
      - 참: 객체 주소 = `slot_page + (page_size - size)`.
      - 거짓: 객체 주소 = `slot_page`.
    - `backtrace`: 할당 백트레이스 문자열.
    - 샘플링 대상이고 사용 가능한 슬롯(`UNUSED` 또는 `FREED`)이 있으면 KFENCE 슬롯 할당, 없으면 일반 SLUB 할당 (`pool_full_fallbacks` 증가).
  - `KFREE`:
    - `ptr`: 해제할 메모리 주소.
    - 대상 슬롯이 `ALLOCATED`이면 `FREED`로 전이하고 페이지 보호 설정.
    - 이미 `FREED`이면 `BUG_KFENCE_DOUBLE_FREE` 발생.
  - `MEMORY_ACCESS`:
    - `addr`, `size`, `is_write`: 접근 주소 및 크기.
    - 접근 범위 `[addr, addr + size - 1]` 중 한 바이트라도 가드 페이지에 걸치면 `CRASH_OOB_GUARD_PAGE`.
    - `FREED` 상태의 슬롯 페이지에 걸치면 `CRASH_USE_AFTER_FREE`.
    - 정상 범위이면 `ACCESS_GRANTED`.

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "page_size": 64,
  "num_slots": 2,
  "sample_interval": 2,
  "active_kfence_objects": 1,
  "freed_kfence_objects": 0,
  "stats": {
    "allocations_requested": 2,
    "kfence_sampled_allocations": 1,
    "regular_slub_allocations": 1,
    "pool_full_fallbacks": 0,
    "frees_count": 0,
    "access_granted_count": 1,
    "oob_guard_detected_count": 1,
    "uaf_detected_count": 0,
    "double_free_detected_count": 0
  },
  "slots": [
    {
      "slot_id": 0,
      "page_addr": 4160,
      "state": "ALLOCATED",
      "ptr": 4184,
      "size": 40,
      "align_right": true,
      "alloc_backtrace": "fs_inode"
    },
    {
      "slot_id": 1,
      "page_addr": 4288,
      "state": "UNUSED",
      "ptr": null,
      "size": 0,
      "align_right": false,
      "alloc_backtrace": null
    }
  ],
  "op_log": [
    {
      "op": "KMALLOC",
      "alloc_id": 1,
      "type": "REGULAR_SLUB",
      "ptr": 65536,
      "size": 32,
      "status": "ALLOCATED_SLUB"
    },
    {
      "op": "KMALLOC",
      "alloc_id": 2,
      "type": "KFENCE",
      "slot_id": 0,
      "ptr": 4184,
      "size": 40,
      "align_right": true,
      "status": "ALLOCATED_OK"
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 4184,
      "size": 40,
      "is_write": false,
      "status": "ACCESS_GRANTED",
      "fault_addr": null
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 4224,
      "size": 4,
      "is_write": false,
      "status": "CRASH_OOB_GUARD_PAGE",
      "fault_addr": 4224
    }
  ]
}
```

---

## 제약 조건

- $16 \le \text{page\_size} \le 4096$ (항상 8의 배수)
- $1 \le \text{num\_slots} \le 32$
- $1 \le \text{sample\_interval} \le 100$
- $1 \le \text{len(operations)} \le 2000$
- 실행 시간 제한: 3.0초 이내
- 메모리 사용 제한: 256MB 이내
