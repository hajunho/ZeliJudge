# DB 쿼리 1개가 조금 느려졌을 뿐인데 왜 전사 카프카 컨슈머가 올스톱되고 메시지가 무한 복제돼요?!: 카프카 컨슈머 리밸런스 폭풍(Kafka Consumer Rebalance Storm)과 max.poll.interval.ms & 협력적 스티키 리밸런싱(Cooperative Sticky Rebalance)

## 1. 실무 시나리오

당신은 대규모 이커머스 결제/주문 시스템의 데이터 파이프라인을 담당하는 백엔드 엔지니어입니다.

현재 주문 체결 토픽(Topic)은 4개의 파티션으로 나뉘어 있고, 2대의 컨슈머 서버(`c1`, `c2`)가 동일한 컨슈머 그룹으로 묶여 초당 수백 건의 주문 이벤트를 안정적으로 컨슘하고 있었습니다.  
그러던 어느 날, 특정 가맹점의 재고 차감 DB 쿼리에 락(Lock) 경합이 발생하여 **단 1건의 주문 메시지를 처리하는 데 350초(약 5분 50초)**가 소요되는 지연이 발생했습니다.

그 순간, 시스템 전체에 초대형 참사가 연쇄 폭발했습니다:
1. 메시지 1건이 350초 걸리는 동안, 해당 컨슈머(`c1`)의 메인 스레드는 다음 `poll()`을 호출하지 못했습니다.
2. 카프카 브로커(Group Coordinator)는 `max.poll.interval.ms`(기본값 300,000ms = 5분)가 초과되자 *"컨슈머 c1이 비정상 종료(Dead/Stalled)되었다"*고 판단하고 그룹에서 강제 추방(Evict)했습니다!
3. 고전적 Eager 리밸런싱이 발동하여 멀쩡히 일하던 `c2`의 파티션까지 몽땅 회수되며 **전사 메시지 처리가 10초 동안 완전 동결(Stop-The-World)**되었습니다.
4. `c1`이 처리 중이던 파티션 0이 `c2`에게 넘어가자, `c1`이 이전에 정상 처리했지만 커밋하지 못했던 앞선 주문 메시지들이 **`c2`에서 처음부터 다시 실행되어 고객들에게 결제가 이중 승인되는 중복 결제 사고**가 터졌습니다!
5. 설상가상으로 `c2` 역시 350초짜리 지연 메시지(Poison Pill)를 만나 또 5분 후 강제 추방당하며 **컨슈머 전원이 무한히 리밸런싱과 중복 처리를 반복하는 연쇄 리밸런스 폭풍(Rebalance Cascade Storm)**에 빠졌습니다!

당신은 카프카 컨슈머 그룹의 폴링 루프와 리밸런싱 메커니즘을 정밀 시뮬레이션하여, `max.poll.interval.ms` 초과 및 독약 메시지(Poison Pill)로 인한 리밸런스 폭풍을 감지하고, `COOPERATIVE_STICKY` 프로토콜과 배치 크기 축소, 그리고 사장 큐(DLQ, Dead Letter Queue) 격리를 통해 시스템을 복구하는 저지 솔루션을 구현해야 합니다.

---

## 2. 시스템 및 리밸런싱 시뮬레이션 규칙

### (1) 파티션 할당 및 폴링 루프
- `num_partitions`개의 파티션(0 ~ $N-1$)이 활성 컨슈머 목록(`active_consumers`)에 라운드로빈 방식으로 균등 할당됩니다.
- 각 컨슈머는 자신의 턴마다 할당된 파티션들에서 아직 커밋되지 않은 오프셋(`committed_offsets[p]`)부터 최대 `max_poll_records`개의 메시지를 한 번의 배치(`batch`)로 폴링합니다.
- 배치 내 모든 메시지의 총 처리 시간은 $T_{batch} = \sum m[	ext{proc\_time\_ms}]$ 입니다.

### (2) `max.poll.interval.ms` 초과 및 장애 판정
1. **정상 처리 완료 ($T_{batch} \le max\_poll\_interval\_ms$)**:
   - 배치의 모든 메시지가 성공적으로 처리됩니다.
   - 각 메시지는 `"COMMITTED"` 상태로 기록되며, 해당 파티션의 커밋 오프셋이 전진합니다: `committed_offsets[p] = max(committed_offsets[p], offset + 1)`.
2. **타임아웃 초과 ($T_{batch} > max\_poll\_interval\_ms$)**:
   - 💥 **`max_poll_interval_violations += 1`, `rebalance_events_count += 1` 기록!**
   - 컨슈머는 브로커에 의해 강제 추방되며, 해당 배치의 메시지들은 커밋되지 못합니다.
   - 타임아웃 발생 전까지 순차 누적 처리된 메시지들은 `"PROCESSED_UNCOMMITTED_DUE_TO_REBALANCE"`로 기록됩니다.
   - 이들 중 커밋되지 못해 향후 다른 컨슈머가 재처리하게 될 메시지 수만큼 `duplicate_processed_count`가 누적됩니다.

### (3) 독약 메시지(Poison Pill)와 사장 큐 (DLQ)
- 동일한 메시지가 리밸런스로 인해 반복 처리 시도된 횟수(`message_attempts[(p, offset)]`)를 추적합니다.
- 특정 메시지의 시도 횟수가 `max_delivery_attempts`(기본값 3)에 도달하면:
  - 영구 장애 메시지(Poison Pill)로 판정되어 **사장 큐(DLQ, Dead Letter Queue)로 격리**됩니다 (`dlq_messages_count += 1`).
  - 파티션이 영구 교착되는 것을 막기 위해 해당 파티션의 커밋 오프셋을 강제로 1 전진시킵니다.

### (4) 리밸런싱 프로토콜 (`assignor`)
- **`"EAGER"` (조급한 리밸런싱)**:
  - 리밸런스 발생 시 그룹 내 모든 컨슈머가 모든 파티션을 강제 반납하며, `total_stw_freeze_ms += rebalance_duration_ms` 만큼 전사 동결됩니다.
- **`"COOPERATIVE_STICKY"` (협력적 스티키 리밸런싱)**:
  - 문제가 발생한 파티션만 점진적으로 재할당되며, 전사 동결 시간이 대폭 절감됩니다 (`total_stw_freeze_ms += rebalance_duration_ms // 4`).

### (5) 최종 시스템 진단 판정 (`overall_verdict`)
- `total_messages == 0`: `"NO_MESSAGES"`
- `max_poll_interval_violations >= 2`: `"REBALANCE_CASCADE_STORM_DATA_DUPLICATION"`
- `max_poll_interval_violations == 1` AND `assignor == "COOPERATIVE_STICKY"`: `"COOPERATIVE_STICKY_RESILIENT"`
- `max_poll_interval_violations == 1`: `"POISON_PILL_SINGLE_REBALANCE"`
- `rebalance_events_count == 0`: `"CLEAN_HIGH_THROUGHPUT"`
- 그 외: `"REBALANCE_RESOLVED"`

---

## 3. 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "num_partitions": 4,
  "consumers": ["c1", "c2"],
  "assignor": "EAGER",
  "max_poll_records": 500,
  "max_poll_interval_ms": 300000,
  "rebalance_duration_ms": 10000,
  "max_delivery_attempts": 3,
  "partition_messages": {
    "0": [
      {"offset": 0, "proc_time_ms": 100},
      {"offset": 1, "proc_time_ms": 350000}
    ],
    "1": [{"offset": 0, "proc_time_ms": 50}],
    "2": [{"offset": 0, "proc_time_ms": 50}],
    "3": [{"offset": 0, "proc_time_ms": 50}]
  }
}
```

---

## 4. 출력 형식 (JSON)

표준 출력(stdout)으로 다음 구조의 JSON 객체를 인덴트(2칸)를 적용하여 출력합니다:

```json
{
  "summary": {
    "num_partitions": 4,
    "consumers": ["c1", "c2"],
    "assignor": "EAGER",
    "max_poll_records": 500,
    "max_poll_interval_ms": 300000,
    "max_delivery_attempts": 3,
    "total_messages": 5,
    "unique_messages_completed": 3,
    "dlq_messages_count": 2,
    "duplicate_processed_count": 3,
    "max_poll_interval_violations": 3,
    "rebalance_events_count": 3,
    "total_stw_freeze_ms": 30000,
    "overall_verdict": "REBALANCE_CASCADE_STORM_DATA_DUPLICATION"
  },
  "sample_records": [
    {
      "consumer": "c1",
      "partition": 0,
      "offset": 0,
      "status": "PROCESSED_UNCOMMITTED_DUE_TO_REBALANCE",
      "attempt": 1
    },
    ...
  ]
}
```
