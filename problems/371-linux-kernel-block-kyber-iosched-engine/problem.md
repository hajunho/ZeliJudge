# Linux Kernel Block Layer Kyber I/O Scheduler: NVMe 초저지연 읽기 보장, 비동기 쓰기 큐 깊이 동적 스케일다운 및 토큰 버킷 스케줄링 엔진

## 문제 설명

현대 데이터센터의 초고속 NVMe SSD 및 플래시 스토리지 환경에서 기존의 레거시 I/O 스케줄러(CFQ, BFQ)는 복잡한 섹터 정렬과 무거운 레드-블랙 트리 락 경합으로 인해 초당 수십만 IOPS를 감당하지 못하고 극심한 CPU 오버헤드를 유발합니다. 반면 아무런 스케줄링도 하지 않는 `none` 스케줄러를 사용할 경우, 백그라운드 대량 비동기 플러시(Buffered Flush Writes, Discard/TRIM)가 하드웨어 큐를 독점하여 포그라운드 동기식 읽기(Sync Reads)의 지연 시간(Tail Latency)이 수십 밀리초로 폭증하는 치명적인 성능 저하가 발생합니다.

페이스북(Meta)의 오메르 펠레그(Omer Peleg)와 옌스 악스보에(Jens Axboe)가 개발하여 리눅스 커널 4.12에 머지된 **카이버(Kyber / `block/kyber-iosched.c`)** 스케줄러는 초고속 스토리지에 특화된 단순하고 강력한 자가 튜닝(Self-Tuning) 멀티큐 I/O 스케줄러입니다:

```
                     [ 사용자 I/O 요청 (blk_mq_make_request) ]
                                         |
               +-------------------------+-------------------------+
               |                                                   |
       [ 동기식 읽기 (READ) ]                             [ 비동기 쓰기 (ASYNC) ]
               |                                                   |
               v                                                   v
        [ read_queue ]                                      [ async_queue ]
  (동기 읽기는 토큰 제한 없음)                            (active_async_tokens 제한 적용)
               |                                                   |
               +-------------------------+-------------------------+
                                         |
                                  (DISPATCH 루프)
                                         v
                         [ NVMe 하드웨어 디스패치 큐 ]
                                         |
                                         v
                        [ 완료 지연시간 샘플링 윈도우 ]
            +---------------------------------------------------------+
            | P99 Read Latency > target_read_lat_us ?                 |
            | - YES (혼잡 발생): async_depth = max(1, async_depth // 2) |
            | - NO (안정 상태): async_depth = min(max_depth, depth + 1) |
            +---------------------------------------------------------+
```

### 핵심 아키텍처 및 스케줄링 메커니즘

1. **2대 도메인 큐 분리 및 디스패치 우선순위**:
   - `READ`: 지연 시간에 극도로 민감한 동기식 읽기 요청. 디스패치 시 항상 1순위로 즉시 하드웨어 큐로 전달됩니다.
   - `ASYNC`: 백그라운드 버퍼드 쓰기 및 트림 요청. 현재 허용된 비동기 토큰(`active_async_tokens`) 한도 내에서만 제한적으로 디스패치되며, 토큰이 고갈되면 큐에 대기(Throttle)합니다.

2. **완료 통계 샘플링 윈도우와 P99 지연 시간 피드백**:
   - `sample_window_reqs`개의 읽기 요청이 완료될 때마다 윈도우 평가를 실행합니다.
   - 윈도우 내 완료된 읽기 지연 시간들의 **99 백분위수(P99 Latency)**를 산출합니다.
   - 만약 P99 지연 시간이 목표치(`target_read_lat_us`)를 초과하면:
     - 스토리지 큐에 혼잡이 발생한 것으로 판단하여 비동기 큐 깊이를 절반으로 급격히 축소합니다(`THROTTLE_SCALE_DOWN`):
       $$	ext{current\_async\_depth} = \max(1, \lfloor 	ext{current\_async\_depth} / 2 floor)$$
   - P99 지연 시간이 목표치 이하로 안정적이면:
     - 대역폭 낭비를 막기 위해 비동기 큐 깊이를 점진적으로 1씩 확장합니다(`EXPAND_SCALE_UP`):
       $$	ext{current\_async\_depth} = \min(	ext{max\_async\_depth}, 	ext{current\_async\_depth} + 1)$$

3. **비동기 토큰 반환 및 활성도 관리**:
   - 디스패치된 비동기 요청(`COMPLETE_BIO`)이 완료되면 소모되었던 비동기 토큰 1개가 즉시 환원됩니다 (`active_async_tokens` 증가, 상한은 `current_async_depth`).

본 문제에서는 이 리눅스 커널 Kyber I/O 스케줄러의 토큰 버킷 큐잉, 우선순위 디스패치, P99 샘플링 피드백 제어 상태 머신을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "target_read_lat_us": 2000,
  "target_sync_write_lat_us": 10000,
  "max_async_depth": 16,
  "initial_async_depth": 8,
  "sample_window_reqs": 4,
  "operations": [
    {"op": "SUBMIT_BIO", "bio_id": "r1", "type": "READ"},
    {"op": "SUBMIT_BIO", "bio_id": "w1", "type": "ASYNC"},
    {"op": "DISPATCH"},
    {"op": "COMPLETE_BIO", "bio_id": "r1", "type": "READ", "latency_us": 1500},
    {"op": "COMPLETE_BIO", "bio_id": "r2", "type": "READ", "latency_us": 1800},
    {"op": "COMPLETE_BIO", "bio_id": "r3", "type": "READ", "latency_us": 1900},
    {"op": "COMPLETE_BIO", "bio_id": "r4", "type": "READ", "latency_us": 2500}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 객체를 공백 없이 출력합니다:

```json
{
  "target_read_lat_us": 2000,
  "target_sync_write_lat_us": 10000,
  "max_async_depth": 16,
  "final_state": {
    "current_async_depth": 4,
    "active_async_tokens": 4,
    "pending_reads": 0,
    "pending_asyncs": 0
  },
  "stats": {
    "reads_dispatched": 1,
    "asyncs_dispatched": 1,
    "asyncs_throttled": 0,
    "window_adjustments": 1,
    "scale_downs": 1,
    "scale_ups": 0
  },
  "op_log": [
    {
      "op": "SUBMIT_BIO",
      "bio_id": "r1",
      "type": "READ",
      "status": "QUEUED_READ"
    }
  ]
}
```
