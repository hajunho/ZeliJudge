# Problem #391: Linux Kernel Block Layer blk-throttle Cgroup I/O Rate Limiting Engine (`block/blk-throttle.c`)

## 문제 설명

대규모 멀티테넌트 클라우드 가상화 및 컨테이너(Kubernetes, Docker) 환경에서 특정 컨테이너가 디스크 I/O를 독점하여 동일 물리 노드의 다른 중요한 서비스(데이터베이스, 웹 서버)를 마비시키는 노이지 이웃(Noisy Neighbor) 문제는 스토리지 QoS의 최대 난제입니다.

리눅스 커널은 블록 레이어(`block/blk-throttle.c`)와 Cgroup v2(`io.max`, `io.weight`)를 통해 프로세스 그룹별로 블록 디바이스 대역폭과 IOPS를 엄격히 제한하는 **blk-throttle (블록 스로틀링)** 서브시스템을 제공합니다:

```
+----------------------------------------------------------------------------------------------------+
|                                Linux Kernel blk-throttle Architecture                              |
+----------------------------------------------------------------------------------------------------+
| [ File System / Page Cache / Direct I/O ]                                                          |
|   | submit_bio(struct bio *bio) -> Dispatches to Block Layer                                       |
+---+------------------------------------------------------------------------------------------------+
| [ Block Layer: block/blk-throttle.c ]                                                              |
|   | 1. Identify cgroup of submitting task (current->cgroups)                                       |
|   | 2. Sliced Token Bucket Accounting: slice_window = 100ms (THROTL_SLICE_USAGE)               |
|   |    B_slice = limit_bps * (slice_window / 1s),  I_slice = limit_iops * (slice_window / 1s)      |
|   | 3. Directional Rate Evaluation (READ vs WRITE separated):                                      |
|   |    - If (bytes + bio_bytes <= B_slice) and (iops + 1 <= I_slice) and (wait_queue is empty):     |
|   |        -> Immediate Dispatch to blk-mq Request Queue!                                          |
|   |    - Else:                                                                                     |
|   |        -> Enqueue bio into throtl_service_queue (wait_queue)!                                  |
|   |        -> Arm kernel high-resolution timer for next slice boundary!                            |
+---+------------------------------------------------------------------------------------------------+
| [ Slice Expiry & Wakeup Workqueue (throtl_dispatch_work) ]                                         |
|   | Advance time to next slice -> Reset bytes_disp/io_disp counters                                |
|   | Dequeue and dispatch pending bios with delay_ms accounting!                                    |
+----------------------------------------------------------------------------------------------------+
```

### 핵심 아키텍처 및 동작 규칙

1. **시간 슬라이스 윈도우 (Time Slice Window)**:
   - 기본 커널 슬라이스 단위는 $100\text{ms}$ (`slice_window_ms = 100`)입니다.
   - 슬라이스당 가용 예산:
     $$B_{\text{slice}} = \lceil \text{limit\_bps} \times (\text{slice\_window\_ms} / 1000) \rceil$$
     $$I_{\text{slice}} = \lceil \text{limit\_iops} \times (\text{slice\_window\_ms} / 1000) \rceil$$
2. **방향별 독립 속도 제어 (Directional Isolation)**:
   - 읽기(`READ`)와 쓰기(`WRITE`)는 별도의 카운터와 상한선(`rbps`, `wbps`, `riops`, `wiops`)을 갖습니다. 한쪽이 포화되어도 다른 방향은 예산이 남아있다면 독립적으로 전달됩니다.
3. **대기 큐 및 순서 보장 (FIFO Backpressure)**:
   - 예산이 소진된 bio는 cgroup의 `wait_queue`로 진입합니다 (`THROTTLED_QUEUED`).
   - 대기 큐에 선행 bio가 대기 중인 경우, 후속 제출되는 bio는 예산 여부와 무관하게 FIFO 순서를 유지하기 위해 대기 큐 후방에 줄을 섭니다.
4. **타이머 만료 및 지연 발송 (`ADVANCE_TIME`)**:
   - 시간이 다음 슬라이스로 진행되면 사용량 카운터가 리셋되고, 큐 전방의 대기 bio들이 순차적으로 디스패치(`DISPATCHED_FROM_QUEUE`)되며 지연 시간(`delay_ms`)이 기록됩니다.

당신은 리눅스 커널 `block/blk-throttle.c`의 슬라이스 토큰 버킷, 방향별 BPS/IOPS 제한 및 큐잉 지연 엔진을 시뮬레이션하는 프로그램을 작성해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "slice_window_ms": 100,
    "cgroups": {
      "cg_db": {
        "rbps": 1048576,
        "wbps": 524288,
        "riops": 100,
        "wiops": 50
      }
    }
  },
  "commands": [
    { "op": "SUBMIT_BIO", "bio_id": "b1", "cgroup_id": "cg_db", "direction": "READ", "size_bytes": 65536, "timestamp_ms": 10 },
    { "op": "SUBMIT_BIO", "bio_id": "b2", "cgroup_id": "cg_db", "direction": "READ", "size_bytes": 65536, "timestamp_ms": 15 },
    { "op": "ADVANCE_TIME", "new_time_ms": 100 }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "current_time_ms": 100,
  "dispatched_count": 2,
  "throttled_count": 1,
  "cgroups": {
    "cg_db": {
      "remaining_wait_queue": 0,
      "current_slice": [100, 200],
      "bytes_disp": { "READ": 65536, "WRITE": 0 },
      "io_disp": { "READ": 1, "WRITE": 0 }
    }
  },
  "events": [ ... ]
}
```
