# 403: 리눅스 커널 스토리지 — 페이지 캐시(Page Cache) 폴리오 리드어헤드(Readahead) 동적 윈도우 스케일링 및 비동기 프리페치 엔진

## 1. 개요 (Overview)

운영체제에서 보조기억장치(NVMe SSD, HDD, 분산 파일 시스템)로부터 데이터를 읽어 들일 때, 애플리케이션이 요청하는 4KB 단위로 매번 동기식 디스크 I/O를 수행하면 극심한 I/O 오버헤드와 장치 인터럽트 지연으로 인해 스토리지 대역폭의 10%도 활용하지 못합니다. 반면, 연속된 대용량 블록을 한 번에 읽어 들이는 순차 I/O는 스토리지 컨트롤러의 처리량을 수 배에서 수십 배 향상시킵니다.

리눅스 커널의 **페이지 캐시 리드어헤드(Readahead, `mm/readahead.c`, `struct file_ra_state`)** 서브시스템은 프로세스의 파일 읽기 패턴을 실시간으로 감시하여, 미래에 접근할 가능성이 높은 페이지들을 사전에 디스크로부터 페이지 캐시(Page Cache)로 당겨오는 적응형 프리페칭 엔진입니다:
1. **순차 패턴 감지 및 동적 윈도우 배수 확장 (Window Doubling)**:
   순차 접근이 지속되면 리드어헤드 윈도우 크기를 $4	ext{KB} 	o 16	ext{KB} 	o 32	ext{KB} \dots 	o 	ext{ra\_max}$로 지수적으로 2배씩 확장하여 대규모 배치 I/O를 실행합니다.
2. **비동기 리드어헤드 마크 (Async Readahead Mark)**:
   현재 읽고 있는 윈도우의 후반부($S - 	ext{async\_size}$)에 비동기 플래그를 설정하여, 애플리케이션이 이 지점을 지나는 순간 **백그라운드 비동기 I/O를 선제 발주**합니다. 애플리케이션 스레드는 I/O 대기 없이 100% 캐시 히트(Cache Hit)로 메모리 버스 속도로 데이터를 읽게 됩니다.
3. **랜덤 탐색 윈도우 축소 (Random Seek Mitigation)**:
   순차성을 벗어난 임의 위치 점프(Seek)나 역방향 탐색이 감지되면, 불필요한 I/O 낭비와 캐시 오염(Cache Thrashing)을 방지하기 위해 윈도우 크기를 즉시 1페이지로 축소합니다.

본 문제에서는 리눅스 커널 페이지 캐시 리드어헤드의 순차성 판정, 윈도우 지수 확장, 비동기 프리페치 마킹 및 발주, 임의 탐색 시 캐시 오염 방지 축소 엔진을 설계 및 구현합니다.

---

## 2. 리드어헤드 상태 머신 다이어그램

```
+========================================================================================+
|                        Linux Page Cache Readahead State Machine                        |
|                                                                                        |
|  Current Readahead Window [ra_start, ra_start + ra_size)                               |
|  +--------------------------------------------+-------------------------------------+  |
|  |     Sync Processing Pages                  |     Async Readahead Trigger Zone    |  |
|  |     [Offset: 0 ... ra_size - async_size)   |     [Offset: ra_size - async_size)  |  |
|  +--------------------------------------------+-------------------------------------+  |
+========================================================================================+
                       ||                                              ||
                       VV                                              VV
        [ Normal In-Cache Hit Stream ]                  [ Hits Async Mark: Trigger NEXT! ]
        - Read latency: ~0ns memory speed               - Issues next window IO in background
                                                        - next_size = min(ra_size * 2, ra_max)
                                                        - Zero Stall for user thread!
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 순차성 판정 (Sequentiality Detection)
이전 읽기 위치 $	ext{prev\_pos}$와 현재 요청 페이지 $P$에 대해:
$$	ext{is\_seq} \iff (P == 	ext{prev\_pos} + 1) \lor (	ext{prev\_pos} == -1 \land P == 0)$$

### 3.2 캐시 미스 및 윈도우 확장
- $P 
otin 	ext{page\_cache}$ (캐시 미스):
  - $	ext{is\_seq} == 	ext{True}$:
    $$	ext{new\_size} = egin{cases} 	ext{ra\_min\_pages} & 	ext{if } 	ext{ra\_size} == 0 \ \min(	ext{ra\_size} 	imes 2, 	ext{ra\_max\_pages}) & 	ext{otherwise} \end{cases}$$
    $	ext{async\_size} = \lfloor 	ext{new\_size} / 2 floor$, 동기식 I/O 발주 (`sync_reads++`).
  - $	ext{is\_seq} == 	ext{False}$ (랜덤 탐색):
    `random_seeks++`, $	ext{ra\_size} = 1$, $	ext{async\_size} = 0$, 단일 페이지 동기식 I/O 발주.

### 3.3 캐시 히트 및 비동기 프리페치 발주
- $P \in 	ext{page\_cache}$ (캐시 히트):
  - 비동기 마크 지점 도달 검사:
    $$P == 	ext{ra\_start} + 	ext{ra\_size} - 	ext{async\_size} \quad (	ext{단, } 	ext{async\_size} > 0)$$
  - 조건을 만족하면 다음 윈도우 $	ext{next\_start} = 	ext{ra\_start} + 	ext{ra\_size}$, $	ext{next\_size} = \min(	ext{ra\_size} 	imes 2, 	ext{ra\_max\_pages})$에 대해 백그라운드 비동기 I/O를 발주 (`async_readaheads++`)하고 상태를 전진시킵니다.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "config": {
    "ra_min_pages": 4,
    "ra_max_pages": 16
  },
  "page_reads": [0, 1, 2, 3, 4, 5]
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "stats": {
    "sync_reads": 1,
    "async_readaheads": 1,
    "cache_hits": 5,
    "cache_misses": 1,
    "io_pages_submitted": 12,
    "random_seeks": 0
  },
  "cached_pages_count": 12,
  "final_ra_window": {
    "start": 4,
    "size": 8,
    "async_size": 4
  }
}
```
