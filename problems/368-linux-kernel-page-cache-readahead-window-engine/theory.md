# Linux Kernel Page Cache Readahead 심층 아키텍처 분석

## 1. 개요 및 배경

스토리지 I/O(NVMe, SATA SSD, HDD)는 DRAM 버스 속도에 비해 수백~수만 배의 지연 시간(Latency)을 갖습니다. 사용자 공간 애플리케이션이 `read()` 시스템 콜을 호출할 때마다 동기적으로 디스크 I/O를 수행한다면, CPU는 지속적으로 I/O Wait 상태에 빠져 전체 시스템 처리량이 극적으로 저하됩니다.

리눅스 커널의 **온디맨드 리드어헤드(On-Demand Readahead)** 알고리즘(`mm/readahead.c`)은 파일 접근의 높은 공간 지역성(Spatial Locality)과 순차적 접근 패턴을 활용하여, 필요한 데이터를 프로세스가 요청하기 직전에 미리 페이지 캐시에 적재합니다.

---

## 2. 파일 리드어헤드 상태 구조체 (`struct file_ra_state`)

각 열린 파일 디스크립터(`struct file`)는 자체적인 리드어헤드 상태를 추적하는 `file_ra_state`를 보유합니다:

```c
struct file_ra_state {
    pgoff_t start;          /* 현재 리드어헤드 윈도우의 시작 페이지 오프셋 */
    unsigned int size;      /* 현재 윈도우 크기 (페이지 수) */
    unsigned int async_size;/* 비동기 프리페치 지점 크기 */
    unsigned int ra_pages;  /* 디바이스 큐에 설정된 최대 리드어헤드 상한 */
    pgoff_t prev_pos;       /* 직전 읽기 오프셋 */
};
```

---

## 3. 핵심 알고리즘 메커니즘

### 3.1 순차성 감지 및 초기 버스트 (Initial Burst)
- 첫 번째 읽기 요청이 발생하거나, 이전 읽기 위치 직후가 요청되면 커널은 순차적 접근으로 분류합니다.
- 초기에는 작은 윈도우(e.g., 4~8 페이지)로 시작하여 불필요한 프리페치로 인한 I/O 대역폭 낭비를 방지합니다.
- 이 초기 읽기는 사용자가 즉시 블록되므로 **동기식(Sync Readahead)**으로 수행됩니다.

### 3.2 루크어헤드 마크 (`PageReadahead` 플래그)
- 리드어헤드 윈도우 내의 특정 페이지(통상 윈도우 끝에서 `async_size`만큼 이전 위치)에 커널은 `PG_readahead` 플래그를 설정합니다.
- 애플리케이션의 순차 읽기 포인터가 이 마크된 페이지에 도달하면, 커널은 사용자가 현재 윈도우의 모든 데이터를 다 읽기 전에 다음 청크를 디스크 컨트롤러에 **비동기식(Async Readahead)**으로 큐잉합니다.
- 이를 통해 I/O 지연 시간이 완전히 은폐(Pipeline Hiding)되어 애플리케이션은 끊김 없는 100% 캐시 히트 속도를 경험합니다.

### 3.3 기하급수적 윈도우 확장 (Exponential Window Doubling)
- 순차 접근이 지속되는 한, 윈도우 크기는 매 트리거마다 2배($2 	imes$)로 증가합니다:
  $$	ext{size}_{k+1} = \min(2 	imes 	ext{size}_k, 	ext{max\_ra\_pages})$$
- 최대 크기(통상 128KB ~ 512KB)에 도달하면 이후부터는 일정한 정상 상태(Steady State) 윈도우를 유지합니다.

### 3.4 랜덤 시크 붕괴 (Window Collapse on Random Seek)
- 순차적 패턴이 깨지고 임의 위치로 시크(`lseek()`, `pread()`)가 발생하면 커널은 잘못된 예측을 막기 위해 리드어헤드 윈도우를 즉시 $0$으로 축소하고 동기식 단일 읽기로 폴백합니다.

---

## 4. 실무 성능 고려사항

1. **SSD vs HDD**: SSD 환경에서는 높은 IOPS와 낮은 탐색 지연 덕분에 비동기 리드어헤드가 더욱 효과적인 파이프라인 처리를 가능하게 합니다.
2. **`posix_fadvise`**:
   - `POSIX_FADV_SEQUENTIAL`: 리드어헤드 윈도우를 최대치(`max_ra_pages`)로 즉시 극대화합니다.
   - `POSIX_FADV_RANDOM`: 리드어헤드를 완전히 비활성화(`ra_pages = 0`)하여 불필요한 캐시 폴루션을 차단합니다.
   - `POSIX_FADV_WILLNEED`: 지정된 범위를 백그라운드에서 강제 사전 로드합니다.
