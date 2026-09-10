# Linux Kernel KASAN (Kernel Address Sanitizer) 섀도우 메모리 1:8 매핑 및 SLUB 격리 큐(Quarantine) 시뮬레이션 엔진

## 문제 설명

리눅스 커널의 **KASAN(Kernel Address Sanitizer, `mm/kasan/generic.c`, `mm/kasan/common.c`, `include/linux/kasan.h`)**은 커널 메모리 버그인 **OOB(Out-of-Bounds Buffer Overflow / Underflow)**와 **UAF(Use-After-Free)**, 그리고 **Double-Free**를 컴파일 타임 코드 계측(GCC/Clang `-fsanitize=kernel-address`) 및 런타임 섀도우 메모리 매핑을 통해 즉각적으로 탐지하는 핵심 서브시스템입니다.

KASAN은 커널 주소 공간의 매 8바이트 메모리 청크를 1바이트의 **섀도우 메모리(Shadow Memory)** 바이트로 1:8 매핑합니다:
$$\text{Shadow Address} = (\text{Addr} \gg 3) + \text{KASAN_SHADOW_OFFSET}$$

섀도우 바이트의 값은 해당 8바이트 메모리 영역의 접근 권한 상태를 나타냅니다:
- `0x00`: 8바이트 전체가 유효하게 접근 가능 (Fully Addressable).
- `1` ~ `7` ($k$): 앞쪽 $k$ 바이트는 정상 접근 가능, 나머지 $(8 - k)$ 바이트는 접근 불가 (Partial Chunk OOB).
- `0xFC` (`KASAN_KMALLOC_REDZONE`): 슬랩 할당 객체 뒤편에 배치된 패딩 레드존 영역.
- `0xFB` (`KASAN_KMALLOC_FREE`): 객체가 해제되어 격리(Quarantine) 큐에 보관 중인 상태.
- `0xFF` (`KASAN_SHADOW_UNMAPPED`): 아직 할당되지 않았거나 완전히 슬랩 캐시로 반환된 미매핑 상태.

또한 KASAN은 할당 해제된 메모리가 즉시 다른 용도로 재할당되어 UAF 탐지를 회피하는 현상을 막기 위해 **Quarantine(격리 큐)** 메커니즘을 운용합니다. 객체가 `kfree()`될 때 메모리는 즉시 슬랩 프리리스트로 반환되지 않고 격리 큐(Ring Buffer)에 들어가 섀도우 값이 `0xFB`로 포이즈닝(Poisoning)됩니다. 격리 큐의 용량(`quarantine_capacity`)이 초과되면 가장 오래된 객체가 방출(Purge)되어 완전히 해제(`0xFF`)됩니다.

본 문제에서는 KASAN의 1:8 섀도우 메모리 매핑, 레드존 패딩 계산, 포인터 정렬, 메모리 접근 유효성 검증(Load/Store 검사), SLUB 격리 큐 상태 전이 및 더블 프리/UAF/OOB 오류 탐지 엔진을 구현해야 합니다.

```
 [커널 가상 메모리 공간 (8 Bytes Chunk)]
 +---+---+---+---+---+---+---+---+  ===>  [섀도우 메모리 (1 Byte)]
 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |        [ 0x00 : 8바이트 전부 접근 가능 ]
 +---+---+---+---+---+---+---+---+
 | 0 | 1 | 2 | 3 | 4 | X | X | X |  ===>  [ 0x05 : 앞 5바이트만 허용, 3바이트 OOB ]
 +---+---+---+---+---+---+---+---+
 | R | R | R | R | R | R | R | R |  ===>  [ 0xFC : 레드존 영역 OOB 탐지 ]
 +---+---+---+---+---+---+---+---+
 | F | F | F | F | F | F | F | F |  ===>  [ 0xFB : 격리 중 (Use-After-Free 탐지) ]
 +---+---+---+---+---+---+---+---+
```

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "memory_size": 256,
  "quarantine_capacity": 4,
  "operations": [
    {
      "op": "KMALLOC",
      "ptr": 16,
      "size": 13,
      "redzone": 8
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 16,
      "size": 13,
      "is_write": false
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 29,
      "size": 1,
      "is_write": true
    },
    {
      "op": "KFREE",
      "ptr": 16
    }
  ]
}
```

### 파라미터 규격
- `memory_size` (정수, 기본 512): 시뮬레이션할 물리/가상 메모리 크기 (바이트 단위, 항상 8의 배수). 섀도우 메모리 크기는 `memory_size // 8`.
- `quarantine_capacity` (정수, 기본 3): 격리 큐가 보관할 수 있는 최대 객체 수.
- `operations` (배열): 순차적으로 실행할 메모리 관리 및 접근 연산 목록.
  - `KMALLOC`:
    - `ptr`: 요청 시작 주소 (정수). 8바이트 단위로 올림 정렬(`(ptr + 7) & ~7`)됩니다.
    - `size`: 요청 페이로드 크기 (바이트, 정수).
    - `redzone`: 뒤편에 붙일 레드존 크기 (바이트, 기본 8).
    - 청크 구성:
      - 완전 유효 청크 개수: `size // 8` -> 각 청크의 섀도우 값 `0`.
      - 나머지 부분 청크: `rem = size % 8`가 0보다 크면 1청크 할당 -> 섀도우 값 `rem`.
      - 레드존 청크 개수: `(redzone + 7) // 8` -> 각 청크의 섀도우 값 `0xFC`.
      - 총 할당 크기: `(full_chunks + (1 if rem > 0 else 0) + redzone_chunks) * 8`.
      - 객체 상태: `"ALLOCATED"`.
  - `KFREE`:
    - `ptr`: 해제할 객체의 시작 주소 (정수).
    - 만약 `ptr`이 이전에 할당된 객체 목록에 없거나, 상태가 이미 `"QUARANTINED"` 또는 `"FREED"`인 경우:
      - 더블 프리 오류(`BUG_DOUBLE_FREE_UNKNOWN_OBJECT` 또는 `BUG_DOUBLE_FREE`) 기록.
    - 정상적인 경우:
      - 객체 상태를 `"QUARANTINED"`로 변경.
      - 객체가 점유하던 모든 청크(총 할당 크기)의 섀도우 값을 `0xFB` (`KASAN_KMALLOC_FREE`)로 포이즈닝.
      - 격리 큐의 맨 뒤에 `ptr` 추가.
      - 만약 격리 큐의 크기가 `quarantine_capacity`를 초과하면, 가장 앞(FIFO)의 객체를 방출(purge)하여 상태를 `"FREED"`로 바꾸고 해당 객체 청크들의 섀도우 값을 `0xFF` (`KASAN_SHADOW_UNMAPPED`)로 초기화.
  - `MEMORY_ACCESS`:
    - `addr`: 접근 시작 바이트 주소 (정수).
    - `size`: 접근 바이트 크기 (기본 1).
    - `is_write`: 쓰기 접근 여부 (불리언, 기본 `false`).
    - 검증 규칙 (`addr`부터 `addr + size - 1`까지의 매 바이트 $b$에 대해):
      - $b < 0$ 또는 $b \ge \text{memory_size}$: 물리 경계 초과 (`OUT_OF_PHYSICAL_BOUNDS`, fault_addr=-1).
      - $b$의 섀도우 바이트 $s = \text{shadow}[b // 8]$, 청크 내 오프셋 $o = b \% 8$:
        - $s == 0$: 정상 접근 가능.
        - $1 \le s \le 7$: $o \ge s$인 경우 슬랩 부분 청크 경계 초과 (`SLAB_OUT_OF_BOUNDS`, fault_addr=$b$).
        - $s == 0xFC$: 레드존 침범 (`SLAB_OUT_OF_BOUNDS`, fault_addr=$b$).
        - $s == 0xFB$: 해제 후 사용 (`USE_AFTER_FREE`, fault_addr=$b$).
        - $s == 0xFF$: 미매핑 메모리 접근 (`UNMAPPED_ACCESS`, fault_addr=$b$).
      - 모든 바이트가 정상인 경우: `ACCESS_GRANTED`.

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마를 따르는 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "memory_size": 256,
  "shadow_size": 32,
  "active_objects": 0,
  "quarantined_objects": 1,
  "stats": {
    "allocations_count": 1,
    "frees_count": 1,
    "access_granted_count": 1,
    "oob_detected_count": 1,
    "uaf_detected_count": 0,
    "double_free_detected_count": 0
  },
  "quarantine_queue": [16],
  "op_log": [
    {
      "op": "KMALLOC",
      "ptr": 16,
      "size": 13,
      "total_alloc_size": 24,
      "status": "ALLOCATED_OK"
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 16,
      "size": 13,
      "is_write": false,
      "status": "ACCESS_GRANTED",
      "fault_addr": null
    },
    {
      "op": "MEMORY_ACCESS",
      "addr": 29,
      "size": 1,
      "is_write": true,
      "status": "SLAB_OUT_OF_BOUNDS",
      "fault_addr": 29
    },
    {
      "op": "KFREE",
      "ptr": 16,
      "status": "QUARANTINED_OK",
      "purged_from_quarantine": null
    }
  ]
}
```

---

## 제약 조건

- $128 \le \text{memory_size} \le 65536$ (항상 8의 배수)
- $1 \le \text{quarantine_capacity} \le 64$
- $1 \le \text{len(operations)} \le 2000$
- $1 \le \text{size} \le 4096$
- 실행 시간 제한: 3.0초 이내
- 메모리 사용 제한: 256MB 이내
