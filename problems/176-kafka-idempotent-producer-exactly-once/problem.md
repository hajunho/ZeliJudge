# Problem 176: Kafka 멱등성 프로듀서(Idempotent Producer)와 Exactly-Once 시뮬레이터

## 문제 설명

대규모 결제 시스템에서 네트워크 패킷 유실로 인해 프로듀서가 전송한 결제 승인 이벤트의 ACK가 유실되자, 프로듀서의 자동 재시도(Retry)로 인해 동일한 결제 건이 브로커 파티션에 2번 이상 중복 저장되어 고객에게 이중 결제가 발생하는 치명적인 금융 사고가 발생했습니다.

기존의 At-Least-Once 메시징은 네트워크 재시도 시 중복을 막을 수 없지만, Apache Kafka의 **KIP-98 멱등성 프로듀서(Idempotent Producer)**는 고유한 **PID (Producer ID)**와 파티션별 단조 증가 **Sequence Number**를 통해 브로커 레벨에서 중복을 원자적으로 제거하고 **정확히 한 번(Exactly-Once Semantics, EOS)**을 보장합니다.

당신은 분산 메시징 미들웨어의 코어 엔진 엔지니어로서, **카프카 브로커의 시퀀스 추적 및 중복 제거(Deduplication)**, **좀비 프로듀서 펜싱(Zombie Fencing)**, 그리고 **트랜잭션 롤백 격리(`read_committed`)** 엔진을 정밀 시뮬레이션해야 합니다.

---

## 시뮬레이터 시스템 명세 및 동작 규칙

### 1. 설정값 (`config`)
- `enable_idempotence` (boolean, 기본값: True): 멱등성 프로듀서 및 시퀀스 추적 활성화 여부.
- `max_in_flight_requests` (int, 기본값: 5): 단일 연결에서 ACK 없이 동시에 날릴 수 있는 최대 인플라이트 요청 수.
- `consumer.isolation_level`: `"read_committed"` (기본값) 또는 `"read_uncommitted"`.

### 2. 이벤트 유형 (`events`)
1. **`REGISTER_PRODUCER`**:
   - `pid`: 프로듀서 고유 ID.
   - `epoch`: 프로듀서 에포크 (인스턴스 세대 번호).
   - 브로커에 프로듀서의 현재 활성 에포크를 등록합니다.
2. **`PRODUCE`**:
   - `pid`: 송신 프로듀서 ID.
   - `epoch`: 송신 프로듀서 에포크.
   - `partition`: 대상 파티션 번호 (기본 0).
   - `seq`: 해당 파티션에 대한 단조 증가 시퀀스 번호 (0부터 시작).
   - `payload`: 메시지 내용.
   - `is_retry`: 네트워크 ACK 유실로 인한 재전송 여부.
3. **`END_TXN`**:
   - `pid`, `epoch`, `partition`: 대상 정보.
   - `commit`: True이면 커밋, False이면 롤백(ABORT).

### 3. 브로커 처리 규칙
1. **좀비 펜싱 (Zombie Fencing)**:
   - 프로듀서의 `epoch`가 브로커에 등록된 최신 에포크보다 낮으면 즉시 거부하고 `ProducerFencedException` 에러를 반환합니다.
2. **멱등성 비활성화 (`enable_idempotence == False`)**:
   - 시퀀스 번호를 검사하지 않고 들어오는 모든 메시지를 파티션 로그에 맹목적으로 추가(`BLIND_APPEND`)합니다.
3. **멱등성 활성화 (`enable_idempotence == True`)**:
   - 해당 `(partition, pid)`의 `last_seq`를 조회합니다:
     - 최초 수신 시: $seq == 0$이어야 성공(`FIRST_SEQ_APPEND`), $seq \ne 0$이면 `OutOfOrderSequenceException`.
     - 후속 수신 시:
       - $seq == \text{last\_seq} + 1$: 정상 순차 메시지. 로그에 추가(`SEQUENTIAL_APPEND`)하고 $\text{last\_seq} \leftarrow seq$.
       - $seq \le \text{last\_seq}$: **중복 메시지 감지!** 로그에 추가하지 않고 성공 상태(`DUPLICATE_DEDUPLICATED`)만 반환.
       - $seq > \text{last\_seq} + 1$: **시퀀스 갭 발생!** `OutOfOrderSequenceException` 반환.
4. **컨슈머 읽기 격리**:
   - `read_committed`: `END_TXN`에서 `commit: false`로 롤백된 PID의 메시지는 제외하고 커밋된 메시지만 반환.
   - `read_uncommitted`: 롤백 여부와 무관하게 모든 비제어 레코드를 반환.

### 4. 최종 판정 (Verdict)
- **`CATASTROPHIC_DUPLICATE_MESSAGE_INJECTION`**: 멱등성 비활성화로 인해 동일 메시지가 로그에 2회 이상 중복 기록된 경우.
- **`ZOMBIE_PRODUCER_FENCED`**: 구 세대 좀비 프로듀서의 쓰기 시도가 차단된 경우.
- **`OUT_OF_ORDER_SEQUENCE_BLOCKED`**: 시퀀스 갭 또는 순서 역전이 감지되어 차단된 경우.
- **`EXACTLY_ONCE_SEMANTICS_GUARANTEED`**: 멱등성 추적을 통해 중복이 원자적으로 제거되거나 정상 순차 처리된 경우.

---

## 입출력 예시

### 입력 (JSON)
```json
{
  "config": { "enable_idempotence": true, "max_in_flight_requests": 5 },
  "consumer": { "isolation_level": "read_committed" },
  "events": [
    { "type": "REGISTER_PRODUCER", "pid": 1001, "epoch": 0 },
    { "type": "PRODUCE", "pid": 1001, "epoch": 0, "partition": 0, "seq": 0, "payload": "pay_order_101", "is_retry": false },
    { "type": "PRODUCE", "pid": 1001, "epoch": 0, "partition": 0, "seq": 0, "payload": "pay_order_101", "is_retry": true }
  ]
}
```

### 출력 (JSON)
```json
{
  "status": "SUCCESS",
  "config": {
    "enable_idempotence": true,
    "isolation_level": "read_committed"
  },
  "metrics": {
    "total_messages_sent": 2,
    "total_retries": 1,
    "deduplicated_messages": 1,
    "fenced_producers": 0,
    "out_of_order_errors": 0,
    "partition_log_length": 1,
    "consumed_records_count": 1,
    "verdict": "EXACTLY_ONCE_SEMANTICS_GUARANTEED"
  },
  "consumed_records": [
    {
      "offset": 0,
      "pid": 1001,
      "epoch": 0,
      "seq": 0,
      "payload": "pay_order_101",
      "is_control": false,
      "tx_id": null
    }
  ]
}
```
