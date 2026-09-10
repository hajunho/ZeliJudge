# Linux Kernel Kmemleak (Kernel Memory Leak Detector) 포인터 스캐닝 및 레드-블랙 트리 할당 추적 엔진

## 문제 설명

리눅스 커널의 **kmemleak(`mm/kmemleak.c`, `include/linux/kmemleak.h`)**은 C 언어로 작성된 커널 환경에서 발생하는 메모리 누수(Memory Leak)를 런타임에 동적으로 감지하는 핵심 메모리 진단 서브시스템입니다.

kmemleak은 사용자 공간의 보수적 가비지 컬렉터(Conservative Garbage Collector, 예: Boehm GC)와 유사하게 메모리 전체를 단어(Word) 단위로 스캔하여 할당된 메모리 블록을 가리키는 유효 포인터가 존재하는지 추적하는 **포인터 스캐닝(Pointer Scanning)** 기법을 사용합니다.

```
 [루트 포인터 (Global/Stack)]
         |
         v
 [kmemleak_object A (1024..1088)] ---> 내부 필드 오프셋 8에 포인터 기록: 2064
                                                        |
                                                        v (Interior Pointer: 2048 <= 2064 < 2048+64)
                                       [kmemleak_object B (2048..2112)]
```

### 핵심 아키텍처 및 3색 마킹(Tri-color Marking)
kmemleak은 모든 활성 할당 객체(`struct kmemleak_object`)를 레드-블랙 트리(Red-Black Tree)로 인덱싱하고, 스캔 주기마다 3색 마킹 알고리즘을 적용합니다:
1. **White (미참조 객체)**:
   - 현재 스캔 주기 동안 유효 참조 횟수(`count`)가 `min_count` 미만인 객체.
   - 도달 불가능(Unreachable) 상태로 간주되며, 잠재적인 메모리 누수 후보(`suspected_leaks`)로 분류됩니다.
   - 연속된 스캔 주기(`unreferenced_cycles`) 동안 계속 미참조 상태가 지속되어 `scan_threshold_cycles`에 도달하면 최종 누수(`confirmed_leaks`)로 확정됩니다.
2. **Gray (스캔 대기 객체)**:
   - 참조 카운트가 `min_count` 이상이거나, 전역 루트/스캔 면제 객체(`min_count == 0`)인 객체.
   - 해당 객체가 점유하는 메모리 범위 내에 다른 객체를 가리키는 포인터가 있는지 조사하기 위해 큐(Gray list)에 삽입됩니다.
3. **Black (스캔 제외/블랙리스트 객체)**:
   - `KMEMLEAK_BLACK` 플래그가 설정된 객체(`KMEMLEAK_IGNORE`). 하드웨어 DMA 버퍼나 펌웨어 영역처럼 포인터 스캔 대상에서 완전히 제외되며, 결코 누수로 보고되지 않습니다.

### 거짓 양성(False Positive) 완화 메커니즘
포인터 태깅, 압축 포인터, 암호화 버퍼 등으로 인해 포인터 스캐너가 도달 가능성을 확인하지 못할 경우를 대비하여 다음과 같은 커널 API가 제공됩니다:
- `KMEMLEAK_IGNORE`: 해당 객체를 블랙리스트 처리하여 스캔 및 누수 보고 대상에서 완전 제외.
- `KMEMLEAK_NOT_LEAK`: 해당 객체의 `min_count`를 0으로 설정하여, 외부 참조가 없더라도 영구 루트(Root)로 취급하고 내부 포인터를 계속 추적.

본 문제에서는 kmemleak의 레드-블랙 트리 객체 범위 검색(`find_object_containing`), 워드 정렬 포인터 스캐닝, 내부 포인터(Interior Pointer) 유효성 판별, 세대별 누수 에이징 카운터 관리 및 거짓 양성 완화 API를 통합한 시뮬레이션 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "pointer_size": 8,
  "scan_threshold_cycles": 2,
  "operations": [
    {
      "op": "KMALLOC",
      "ptr": 1024,
      "size": 64,
      "min_count": 1,
      "backtrace": "vfs_alloc_inode"
    },
    {
      "op": "ADD_ROOT_POINTER",
      "target_ptr": 1024
    },
    {
      "op": "SCAN"
    }
  ]
}
```

### 파라미터 규격
- `pointer_size` (정수, 기본 8): 아키텍처 포인터 크기 (바이트 단위, 통상 4 또는 8). 모든 포인터 읽기/쓰기는 `pointer_size` 단위로 정렬됩니다.
- `scan_threshold_cycles` (정수, 기본 2): 확정 누수(`confirmed_leaks`)로 보고되기 위해 연속으로 미참조되어야 하는 최소 스캔 주기 수.
- `operations` (배열): 순차 실행할 메모리 및 kmemleak 명령 목록.
  - `KMALLOC`:
    - `ptr`: 시작 가상 주소 (정수). `(ptr + (pointer_size - 1)) & ~(pointer_size - 1)`로 정렬.
    - `size`: 블록 크기 (바이트, 정수).
    - `min_count`: 최소 유효 참조 수 (정수, 기본 1).
    - `is_black`: 블랙리스트 여부 (불리언, 기본 `false`).
    - `backtrace`: 할당 호출 스택 문자열 (기본 `"unknown"`).
  - `KFREE`:
    - `ptr`: 해제할 객체 주소. 객체 상태를 `"FREED"`로 변경하고 해당 객체가 점유하던 메모리 워드를 모두 삭제.
  - `ADD_ROOT_POINTER`:
    - `target_ptr`: 루트 포인터 목록에 추가할 주소.
  - `REMOVE_ROOT_POINTER`:
    - `target_ptr`: 루트 포인터 목록에서 제거할 주소.
  - `WRITE_POINTER`:
    - `src_addr`, `offset`, `target_ptr`: 주소 `(src_addr + offset)`에 포인터 값 `target_ptr` 기록.
  - `KMEMLEAK_IGNORE`:
    - `ptr`: 대상 객체를 `is_black = true`로 변경.
  - `KMEMLEAK_NOT_LEAK`:
    - `ptr`: 대상 객체의 `min_count = 0`으로 변경.
  - `SCAN`:
    - 전체 포인터 스캔 및 3색 마킹 BFS 탐색 수행, 미참조 객체 에이징 카운터 갱신 및 의심/확정 누수 집계.

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "pointer_size": 8,
  "scan_threshold_cycles": 2,
  "active_objects_count": 1,
  "stats": {
    "total_allocations": 1,
    "total_frees": 0,
    "scan_runs": 1,
    "suspected_leaks_count": 0,
    "confirmed_leaks_count": 0,
    "false_positive_mitigations": 0
  },
  "scan_history": [
    {
      "scan_id": 1,
      "gray_count": 1,
      "suspected_leaks": [],
      "confirmed_leaks": []
    }
  ],
  "active_objects": [
    {
      "ptr": 1024,
      "size": 64,
      "count": 1,
      "min_count": 1,
      "is_black": false,
      "unreferenced_cycles": 0,
      "backtrace": "vfs_alloc_inode"
    }
  ],
  "op_log": [
    {
      "op": "KMALLOC",
      "ptr": 1024,
      "size": 64,
      "status": "TRACKED"
    },
    {
      "op": "ADD_ROOT_POINTER",
      "target_ptr": 1024,
      "status": "ROOT_ADDED"
    },
    {
      "op": "SCAN",
      "scan_id": 1,
      "suspected_leaks_count": 0,
      "confirmed_leaks_count": 0
    }
  ]
}
```

---

## 제약 조건

- $4 \le \text{pointer\_size} \le 8$
- $1 \le \text{scan\_threshold\_cycles} \le 10$
- $1 \le \text{len(operations)} \le 1000$
- $1 \le \text{size} \le 16384$
- 실행 시간 제한: 3.0초 이내
- 메모리 사용 제한: 256MB 이내
