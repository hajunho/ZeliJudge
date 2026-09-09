# Problem 242: Apache Kafka: 트랜잭션 프로듀서 행(Hang), Last Stable Offset (LSO) 정체 및 `read_committed` 컨슈머 랙 폭증 장애

## 1. 개요 및 배경 시나리오

전자상거래 주문 결제 시스템, 핀테크 송금 파이프라인, 그리고 실시간 스트림 프로세싱(Apache Flink, Kafka Streams) 환경에서는 데이터의 중복 처리나 유실을 원천 방지하기 위해 **Kafka 트랜잭션(Exactly-Once Semantics, EOS)**을 도입합니다.

Kafka 트랜잭션 파이프라인에서 프로듀서는 `transactional.id`를 발급받아 원자적 쓰기를 수행하고, 다운스트림 서비스의 컨슈머는 **`isolation.level = read_committed`** 격리 수준을 설정하여 커밋된 메시지만 안전하게 소비합니다.

```
                      Kafka 파티션 오프셋과 격리 수준 뷰
                      
 Log Offset:   0       1       2       3       4     ...    150     151    (LEO)
             ┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───────┬───────┬──────┐
 Partition 0 │ C │ C │ C │ T │ N │ N │ N │ N │ N │  ...  │   N   │      │
             └───┴───┴───┴───┴───┴───┴───┴───┴───┴───────┴───────┴──────┘
                           ▲                                      ▲
                           │                                      │
                          LSO                                    HW
                 (Last Stable Offset)                      (High Watermark)
                           │                                      │
                           ▼                                      ▼
             [read_committed 컨슈머 멈춤]               [read_uncommitted 컨슈머]
             (오프셋 3번 트랜잭션 미완결로 인해                (커밋 여부 상관없이
              이후 정상 메시지 소비 불가!)                   150번까지 모두 읽음)
```

그러나 트랜잭션이 활성화된 프로덕션 클러스터에서 다음과 같은 치명적인 파이프라인 정체 장애가 빈번히 발생합니다:

1. **트랜잭션 프로듀서 행(Hang)에 의한 LSO 고갈 및 컨슈머 랙 폭증 (`LSO_STALL_CONSUMER_LAG_EXPLOSION`)**:
   - 트랜잭션 프로듀서가 오프셋 3번 위치에서 트랜잭션을 시작(`TXN_BEGIN`)하고 메시지를 1건 전송한 후, 외부 데이터베이스 락 경합이나 JVM Full GC, 네트워크 단절로 인해 멈춤(Hang) 상태에 빠짐.
   - 그 사이 동일 파티션으로 유입되는 수많은 비트랜잭션(Non-transactional) 메시지들이 오프셋 150번까지 정상 적재되어 High Watermark(HW)는 계속 전진함.
   - 그러나 Kafka 브로커의 **Last Stable Offset(LSO)**은 아직 완료되지 않은 최초의 미완결 트랜잭션 오프셋(`FirstUnstableOffset` = 3)에 **완전히 묶여서 멈추게 됨**.
   - `read_committed` 컨슈머는 LSO를 넘어설 수 없으므로, 뒤이어 들어온 수십만 건의 정상 메시지를 전혀 읽지 못하고 **컨슈머 랙(Consumer Lag)이 수만~수십만 건으로 폭증**하며 전사 다운스트림 처리가 마비됨.

2. **과도하게 긴 트랜잭션 타임아웃 지연 (`EXCESSIVE_TRANSACTION_TIMEOUT_DELAY`)**:
   - Kafka의 기본 `transaction.timeout.ms`가 60,000ms(1분, 과거 버전은 15분)로 설정되어 있어, 프로듀서 프로세스가 완전히 사망했음에도 트랜잭션 코디네이터가 타임아웃을 감지하고 `ABORT` 마커를 찍을 때까지 LSO가 풀리지 않아 장시간 서비스 마비 지속.

3. **코디네이터 에포크 펜싱 및 좀비 프로듀서 차단 (`ZOMBIE_PRODUCER_SPLIT_BRAIN_ATTEMPT`)**:
   - 코디네이터가 타임아웃으로 트랜잭션을 강제 폐기(`ABORT`)하고 프로듀서 에포크(Epoch)를 1 증가시킴.
   - 뒤늦게 깨어난 좀비 프로듀서가 이전 에포크로 메시지를 쓰려 할 때, 브로커가 이를 즉각 차단(`ProducerFencedException`)하지 못하면 데이터 오염이 발생함.

4. **`read_uncommitted` 컨슈머의 더티 리드 재앙 (`READ_UNCOMMITTED_DIRTY_READ`)**:
   - 일부 컨슈머가 기본값인 `read_uncommitted`로 설정되어 있는 경우, 나중에 롤백(`ABORT`)되어 폐기된 트랜잭션 메시지를 읽어 결제 중복 승인이나 잘못된 원장 처리를 유발함.

본 과제에서는 Kafka 트랜잭션 코디네이터, 파티션 로그(HW, LSO, LEO), 프로듀서 에포크 펜싱, 격리 수준별 컨슈머 소비 동작을 정확히 시뮬레이션하고 문제를 분석 및 해결해야 합니다.

---

## 2. 상태 머신 및 동작 명세

시뮬레이터는 클러스터 환경 설정(`config`), 프로듀서 메타데이터(`producers`), 그리고 일련의 이벤트(`events`)를 처리합니다.

### 2.1 오프셋 계산 규칙
- **LEO (Log End Offset)**: 다음에 기록될 오프셋 (초기값 0).
- **HW (High Watermark)**: 복제가 완료된 최신 오프셋 (본 시뮬레이션에서는 기록 즉시 HW = LEO).
- **LSO (Last Stable Offset)**:
  - 현재 진행 중인 미완결 트랜잭션(`open_transactions`)이 없는 경우: $\text{LSO} = \text{HW}$.
  - 진행 중인 트랜잭션이 존재하는 경우: $\text{LSO} = \min(\text{tx.start\_offset})$.

### 2.2 격리 수준별 컨슈머 소비 규칙 (`CONSUME_POLL`)
- **`read_uncommitted`**:
  - `consumer_offset`부터 `HW`까지 모든 데이터 메시지를 소비합니다.
  - 이 과정에서 나중에 `ABORTED`된 트랜잭션 메시지를 소비하면 `dirty_reads_detected`가 활성화됩니다.
- **`read_committed`**:
  - `consumer_offset`부터 **`LSO`**까지만 소비할 수 있습니다 (LSO 이후의 메시지는 접근 불가).
  - 소비 범위 내에서:
    - 상태가 `COMMITTED`인 메시지만 유효하게 소비(`total_consumed` 증가).
    - 상태가 `ABORTED`인 메시지는 스킵(`aborted_messages_skipped` 증가).
    - 트랜잭션 제어 마커(`COMMIT`/`ABORT` 마커)는 내부 제어용이므로 컨슈머에 전달되지 않고 스킵.
  - 현재 랙: $\text{current\_lag} = \text{HW} - \text{consumer\_offset}$.

### 2.3 이벤트 타입 (`events`)
1. **`TXN_BEGIN`**: 프로듀서의 신규 트랜잭션 개시. 에포크 검증.
2. **`PRODUCE` / `PRODUCE_BURST`**: 메시지 발행. 트랜잭션 진행 중인 경우 해당 트랜잭션의 `messages` 목록에 포함되고 로그 상태는 `PENDING`으로 기록. 비트랜잭션인 경우 `COMMITTED`로 기록.
3. **`PRODUCER_HANG`**: 프로듀서가 멈춤 상태에 진입하여 커밋/어보트를 호출하지 못함.
4. **`TXN_COMMIT`**: 정상 커밋. 트랜잭션 메시지들을 `COMMITTED`로 변경하고 파티션 로그에 `COMMIT` 제어 마커 추가.
5. **`TXN_ABORT`**: 롤백. 트랜잭션 메시지들을 `ABORTED`로 변경하고 파티션 로그에 `ABORT` 제어 마커 추가.
6. **`COORDINATOR_TICK`**: 트랜잭션 코디네이터의 주기적 감시 틱. 경과 시간($\text{time\_ms} - \text{start\_time\_ms} \ge \text{transaction\_timeout\_ms}$) 초과 시:
   - 해당 트랜잭션을 강제 `ABORT` 처리하고 `ABORT` 마커 기록.
   - 프로듀서 에포크를 증가시켜 좀비 프로듀서를 펜싱(`fenced_producers`).
7. **`CONSUME_POLL`**: 컨슈머 폴링 수행.

---

### 2.4 감지해야 할 이상 징후 (`anomalies`) 및 권장안 (`recommendations`)

- `"LSO_STALL_CONSUMER_LAG_EXPLOSION"`:
  - `read_committed` 모드에서 미완결 트랜잭션으로 인해 LSO 정체가 발생하고, 최대 컨슈머 랙이 100건 이상 치솟은 경우.
  - 권장안: `"TUNE_TRANSACTION_TIMEOUT_MS_AND_MONITOR_LSO"`
- `"EXCESSIVE_TRANSACTION_TIMEOUT_DELAY"`:
  - 트랜잭션 타임아웃이 60,000ms 이상으로 길고 LSO 정체 지속 시간이 30,000ms 이상 지속된 경우.
  - 권장안: `"LOWER_TRANSACTION_TIMEOUT_MS_TO_REDUCE_BLOCKED_WINDOW"`
- `"ZOMBIE_PRODUCER_SPLIT_BRAIN_ATTEMPT"`:
  - 코디네이터에 의해 에포크가 펜싱된 좀비 프로듀서가 쓰기를 시도하여 차단된 경우.
  - 권장안: `"ENFORCE_TRANSACTIONAL_ID_AND_EPOCH_FENCING"`
- `"READ_UNCOMMITTED_DIRTY_READ"`:
  - `read_uncommitted` 컨슈머가 롤백/어보트된 더티 메시지를 읽은 경우.
  - 권장안: `"SET_CONSUMER_ISOLATION_LEVEL_TO_READ_COMMITTED"`

---

## 3. 입력 형식 (`sys.stdin`)

표준 입력으로 단일 JSON 객체가 주어집니다.

```json
{
  "config": {
    "topic": "orders.payment.tx",
    "partition_id": 0,
    "consumer_isolation_level": "read_committed",
    "transaction_timeout_ms": 20000,
    "producer_epoch_fencing_enabled": true
  },
  "producers": [
    {"producer_id": "tx-prod-1", "transactional_id": "txn-order-1", "initial_epoch": 0},
    {"producer_id": "non-tx-prod-2", "transactional_id": null}
  ],
  "events": [
    {"time_ms": 1000, "type": "TXN_BEGIN", "producer_id": "tx-prod-1"},
    {"time_ms": 1500, "type": "PRODUCE", "producer_id": "tx-prod-1", "message_id": "tx-msg-1", "payload": "Order 1"},
    {"time_ms": 2000, "type": "PRODUCER_HANG", "producer_id": "tx-prod-1"},
    {"time_ms": 3000, "type": "PRODUCE_BURST", "producer_id": "non-tx-prod-2", "count": 200},
    {"time_ms": 5000, "type": "CONSUME_POLL", "consumer_id": "c-1"},
    {"time_ms": 22000, "type": "COORDINATOR_TICK"},
    {"time_ms": 23000, "type": "CONSUME_POLL", "consumer_id": "c-1"}
  ]
}
```

---

## 4. 출력 형식 (`sys.stdout`)

표준 출력으로 JSON 객체를 단일 행으로 출력합니다 (`ensure_ascii=False`).

```json
{
  "topic": "orders.payment.tx",
  "partition_id": 0,
  "isolation_level": "read_committed",
  "total_messages_produced": 201,
  "total_messages_consumed": 200,
  "aborted_messages_skipped": 1,
  "max_consumer_lag": 201,
  "lso_stalled_duration_ms": 17000,
  "current_lso": 202,
  "current_hw": 202,
  "zombie_fenced_attempts": 0,
  "anomalies": [
    "LSO_STALL_CONSUMER_LAG_EXPLOSION"
  ],
  "recommendations": [
    "TUNE_TRANSACTION_TIMEOUT_MS_AND_MONITOR_LSO"
  ],
  "diagnosis": "미완결 트랜잭션으로 인해 LSO가 고정(LSO=202, HW=202)되어 read_committed 컨슈머 랙이 최대 201개까지 폭증함."
}
```
