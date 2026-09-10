# Linux Kernel Page Cache Readahead: 온디맨드 윈도우 배가(Window Doubling), 비동기 루크어헤드 마크 및 순차성 감지 엔진

## 문제 설명

리눅스 커널의 **페이지 캐시 리드어헤드(`mm/readahead.c`, `include/linux/pagemap.h`)**는 프로세스가 파일 데이터를 순차적으로 읽어 들일 때, 디스크 I/O 대기 지연(Latency)을 은폐하기 위해 향후 요청될 페이지들을 백그라운드에서 미리 프리페치(Prefetch)하는 핵심 성능 최적화 서브시스템입니다.

```
       [ 사용자 공간 읽기 요청 (read/pread) ]
                         |
                         v
     +---------------------------------------+
     | 순차성 판별 (Sequentiality Detection)  |
     +---------------------------------------+
       |                                   |
    [ 순차적 읽기 ]                     [ 랜덤 시크 (Random Seek) ]
       |                                   |
       v                                   v
+-----------------------------+     +-------------------------------+
| 온디맨드 윈도우(Window) 관리  |     | 윈도우 즉시 붕괴 (Size = 0)   |
| 1. 초기 버스트 (Sync)       |     | 동기식 단일 읽기 (Sync Read)   |
| 2. 루크어헤드 도달 시 비동기  |     +-------------------------------+
|    윈도우 2배 확장 (Async)   |
+-----------------------------+
       |
       v
 [ 페이지 캐시 할당 & 디스크 I/O 발행 ]
```

### 핵심 아키텍처 및 메커니즘

1. **순차성 감지 (Sequentiality Detection)**:
   - 파일 읽기 오프셋이 $0$이거나, 직전 읽기 요청의 끝 페이지 번호 직후(`prev_page + 1`)와 일치하면 순차적 스트림(Sequential Stream)으로 판정합니다.
   - 직전 읽기 오프셋과 연속되지 않는 주소로 점프하면 **랜덤 시크(Random Seek)**가 감지됩니다.
   - 랜덤 시크 시:
     - 현재 리드어헤드 윈도우는 즉시 붕괴(`size = 0, async_size = 0, lookahead_index = -1`)합니다.
     - 요청된 페이지 중 캐시에 없는 페이지만을 동기식으로 디스크에서 읽어옵니다(`RANDOM_SEEK_SYNC_READ`).
     - `random_seeks_detected` 통계가 증가합니다.

2. **초기 동기 리드어헤드 버스트 (`SYNC_READAHEAD_INITIAL_BURST`)**:
   - 윈도우 크기가 $0$인 상태에서 순차 읽기가 시작되면, 커널은 `initial_ra_pages` 크기의 윈도우를 동기식으로 생성하여 디스크 I/O를 발행합니다.
   - `size = min(initial_ra_pages, max_ra_pages)`
   - `start = offset_page`
   - `async_size = max(1, int(size * async_ratio))`
   - `lookahead_index = start + size - async_size` (이 위치에 커널은 `PageReadahead` 마크를 부여합니다).

3. **루크어헤드 마크 비동기 확장 (`ASYNC_READAHEAD_WINDOW_EXPANDED`)**:
   - 순차 읽기가 진행되다가 `offset_page == lookahead_index`에 도달하면, 커널은 사용자가 이전 프리페치 데이터의 끝에 도달하기 전에 미리 다음 청크를 비동기식 I/O로 채우기 위해 윈도우를 2배로 확장합니다.
   - `new_size = min(size * 2, max_ra_pages)`
   - `new_start = start + size`
   - `new_async = max(1, int(new_size * async_ratio))`
   - `new_lookahead_index = new_start + new_size - new_async`
   - `[new_start, new_start + new_size)` 범위의 미캐시 페이지들을 백그라운드 프리페치합니다.

4. **페이지 캐시 히트 및 퍼지**:
   - `CACHE_HIT`: 읽기 범위의 페이지들이 이미 캐시에 존재하며 루크어헤드 트리거가 발생하지 않은 일반적인 히트 상태입니다.
   - `DROP_PAGE_CACHE`: `posix_fadvise(DONTNEED)` 또는 메모리 압박으로 인해 캐시가 모두 방출될 때, 캐시된 모든 페이지를 삭제하고 리드어헤드 윈도우를 리셋합니다.

본 문제에서는 위 리눅스 커널 페이지 캐시 온디맨드 리드어헤드 상태 머신과 I/O 회계 통계를 충실히 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "max_ra_pages": 16,
  "initial_ra_pages": 4,
  "async_ratio": 0.5,
  "operations": [
    {"op": "FILE_READ", "offset_page": 0, "nr_pages": 1},
    {"op": "FILE_READ", "offset_page": 1, "nr_pages": 1},
    {"op": "FILE_READ", "offset_page": 2, "nr_pages": 1},
    {"op": "FILE_READ", "offset_page": 3, "nr_pages": 1},
    {"op": "FILE_READ", "offset_page": 50, "nr_pages": 1}
  ]
}
```

### 파라미터 규격
- `max_ra_pages` (정수, 기본 32): 허용되는 최대 리드어헤드 윈도우 크기 (페이지 단위).
- `initial_ra_pages` (정수, 기본 4): 최초 순차 스트림 발견 시 프리페치할 초기 페이지 수.
- `async_ratio` (실수, 기본 0.5): 윈도우 크기 대비 비동기 트리거 지점 비율.
- `operations` (배열): 파일 I/O 및 캐시 제어 연산 목록.
  - `FILE_READ`: `offset_page` (시작 페이지 번호), `nr_pages` (읽을 페이지 수, 기본 1).
  - `DROP_PAGE_CACHE`: 페이지 캐시 전체 제거 및 윈도우 초기화.

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 객체를 공백 없이 출력합니다:

```json
{
  "max_ra_pages": 16,
  "initial_ra_pages": 4,
  "async_ratio": 0.5,
  "cached_pages_count": 13,
  "final_window": {
    "start": 50,
    "size": 0,
    "async_size": 0,
    "lookahead_index": -1
  },
  "stats": {
    "read_requests": 5,
    "cache_hits": 4,
    "cache_misses": 5,
    "sync_ra_count": 1,
    "async_ra_count": 1,
    "pages_read_from_disk": 13,
    "random_seeks_detected": 1
  },
  "op_log": [
    {
      "op": "FILE_READ",
      "offset_page": 0,
      "nr_pages": 1,
      "status": "SYNC_READAHEAD_INITIAL_BURST",
      "ra_window_size": 4,
      "lookahead_index": 2,
      "pages_fetched": 4
    }
  ]
}
```
