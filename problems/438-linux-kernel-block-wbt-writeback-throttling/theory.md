# Theory #438: 리눅스 커널 블록 레이어: block/blk-wbt.c 라이트백 스로틀링 및 지연 시간 제어 이론

## 1. 스토리지 버퍼블로트(Bufferbloat)와 비대칭 I/O의 병목 역학

현대 엔터프라이즈 운영체제에서 메모리와 스토리지 간 속도 차이를 은폐하기 위해 페이지 캐시(Page Cache)와 지연 쓰기(Buffered Write / Writeback)는 필수적인 메커니즘입니다. 애플리케이션이 `write()` 시스템 콜을 호출하면 데이터는 즉각 DRAM 페이지 캐시에 기록되고 `dirty` 플래그만 설정된 채 사용자에게 즉시 리턴합니다.

그러나 이 구조는 다음과 같은 파괴적인 부작용을 유발합니다:
1. **대량 더티 데이터 축적**: 64GB 시스템에서 dirty background ratio가 10%라면 약 6.4GB의 더티 메모리가 한순간에 쌓입니다.
2. **플러시 스톰 (Flusher Storm)**: 플러시 스레드(`kworker/flush`)가 동작을 개시하면 기가바이트 단위의 쓰기 요청이 I/O 스케줄러와 스토리지 디바이스 큐(NVMe/SAS)로 쏟아집니다.
3. **읽기 기아 및 지연 스파이크**: 스토리지 컨트롤러 내부의 버퍼와 플래시 변환 계층(FTL) 큐가 수백 개의 대형 순차 쓰기 요청으로 가득 차게 되며, 이때 발생하는 단일 4KB 읽기(예: 데이터베이스 B-Tree 인덱스 탐색, 프로세스 실행 시 `mmap` 폴트)는 큐의 맨 뒤에서 수백 밀리초 동안 대기하게 됩니다.

---

## 2. WBT (Writeback Throttling)의 수학적 모델 및 설계 원리

Jens Axboe가 설계한 **WBT (`block/blk-wbt.c`)**는 네트워크의 CoDel(Controlled Delay) 및 TCP 혼잡 제어(AIMD) 알고리즘에서 영감을 받아 블록 계층에 맞게 재구성된 지연 시간 제어 체계입니다.

```
+-------------------------------------------------------------------+
|                        Linux Block Layer                          |
|                                                                   |
|   Application bio submit (submit_bio / blk_mq_submit_bio)         |
|                            │                                      |
|                            ▼                                      |
|                 wbt_wait() Throttling Hook                        |
|                            │                                      |
|       ┌────────────────────┼────────────────────┐                 |
|       ▼                    ▼                    ▼                 |
|    REQ_OP_READ         REQ_SYNC             REQ_WB                |
|       │                    │                    │                 |
|   Bypass WBT           Bypass WBT        Inflight < cur_depth?    |
|   (Issue Direct)       (Issue Direct)      ┌────┴────┐            |
|       │                    │              Yes        No           |
|       │                    │               │         │            |
|       │                    │               ▼         ▼            |
|       │                    │         Issue Direct   wbt_wait()    |
|       │                    │               │        (Sleep in FIFO)
|       ▼                    ▼               ▼         │            |
|   [================== blk-mq Hardware Queues ==================]  |
|                            │                         │            |
|                            ▼                         ▼            |
|                 wbt_done() Completion Hook ◄─────────┘            |
|                            │                                      |
|            ┌───────────────┴───────────────┐                      |
|            ▼                               ▼                      |
|       READ latency                    WB Finished                 |
|   add_sample(duration)             Wake up pending wbt            |
|            │                                                      |
|            ▼                                                      |
|   wbt_update_limits() Window Timer (100ms)                        |
|   Compare P90(latency) vs target_lat_us:                          |
|   - Exceeded: cur_depth = max(min_depth, cur_depth / 2)           |
|   - Normal:   cur_depth = min(max_depth, cur_depth + step)        |
+-------------------------------------------------------------------+
```

### (1) AIMD (Additive Increase, Multiplicative Decrease) 수식화
WBT의 큐 깊이 제어 $D(t)$는 시간 윈도우 $t$에 대해 다음과 같이 정의됩니다:

$$D(t+1) = \begin{cases} 
\max(D_{\min}, \lfloor D(t) / 2 \rfloor) & \text{if } L_{P90}(t) > L_{\text{target}} \\
\min(D_{\max}, D(t) + \Delta_{\text{step}}) & \text{if } L_{P90}(t) \le L_{\text{target}} \text{ and } N_{\text{samples}} > 0 \\
D(t) & \text{if } N_{\text{samples}} = 0 \text{ (Idle)}
\end{cases}$$

여기서:
- $L_{P90}(t)$: 해당 윈도우 내에서 측정된 읽기 완료 지연 시간의 90번째 백분위수.
- $L_{\text{target}}$: 스토리지 미디어의 특성에 맞춘 SLA 목표 지연 시간 (예: 고성능 NVMe는 $2000 \mu s$, SATA SSD는 $5000 \mu s$, 기계식 HDD는 $75000 \mu s$).
- $D_{\min}$: 최소 큐 깊이로, 쓰기 작업이 완전히 굶어 죽는(Starvation) 현상을 방지하는 안전 하한선.
- $\Delta_{\text{step}}$: 혼잡이 완화되었을 때 단계적으로 처리량을 회복시키는 증량 단위.

### (2) 왜 평균이 아닌 90/99 백분위수(Percentile)인가?
평균 지연 시간(Mean Latency)은 수많은 빠른 캐시 적중이나 가벼운 읽기에 의해 왜곡(Skew)됩니다.
실제 사용자가 체감하는 시스템 멈춤(Jank)과 서비스 SLA 위반은 P90 및 P99 꼬리 지연(Tail Latency)에 의해 결정됩니다. 따라서 WBT는 윈도우 내 상위 백분위 지연을 기준으로 판단하여 스토리지 큐 내의 잠재적 체류 시간을 즉각적으로 포착합니다.

---

## 3. 리눅스 blk-mq 다중 큐 아키텍처와의 통합

현대 NVMe SSD는 수십~수백 개의 하드웨어 큐(Hardware Submission Queues)를 병렬로 운용합니다.
`blk-mq` 환경에서 WBT는 각 CPU 코어의 소프트웨어 스테이징 큐와 하드웨어 디스패치 큐 사이의 관문 역할을 수행합니다:
1. **wbt_wait()**: 백그라운드 플러셔 스레드가 I/O를 제출하려 할 때, 전역 또는 노드별 비동기 쓰기 카운터가 `cur_depth`에 도달했는지 검사합니다. 만약 초과했다면 태스크는 `TASK_UNINTERRUPTIBLE` 상태로 대기 큐(`wait_queue_head_t`)에 진입합니다.
2. **wbt_done()**: 디바이스 인터럽트 완료 핸들러가 I/O 완료를 보고하면 카운터를 감소시키고, 대기 중인 비동기 쓰기 태스크를 깨워 다음 요청을 제출할 수 있도록 허용합니다.
3. **결과적인 격리 효과**: 이 구조를 통해 아무리 무거운 `sync`나 대용량 파일 복사 작업이 백그라운드에서 실행되더라도, 대화형 읽기 요청은 항상 큐 깊이 $D_{\min} \sim D_{\max}$ 사이의 제어된 버퍼 크기만을 마주하게 되어 예측 가능한 밀리초 단위 지연 시간을 보장받습니다.
