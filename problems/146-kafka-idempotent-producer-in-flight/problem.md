# [카프카는 파티션 순서를 보장한다면서요?!: Kafka 프로듀서 멱등성(Idempotent Producer)과 max.in.flight.requests.per.connection 순서 역전 및 중복 참사]

## 1. 장애 시나리오: "순서대로 쏜 결제 이벤트가 뒤집혀 배송이 주문보다 먼저 생성된 대참사"

이커머스 결제 파이프라인에서 주문-결제-배송 이벤트를 Kafka 단일 토픽/단일 파티션으로 순차 발행하는 프로듀서 시스템을 운영 중이었습니다:
```text
Event #1 (Seq 0): ORDER_CREATED      (주문 생성)
Event #2 (Seq 1): PAYMENT_COMPLETED  (결제 완료)
Event #3 (Seq 2): SHIPPING_REQUESTED (배송 요청)
```

어느 날 새벽, 일시적인 네트워크 회선 순단(Packet Loss & Reorder)이 발생한 뒤, 다운스트림 결제/배송 컨슈머에서 치명적인 에러가 폭발했습니다:
```text
ERROR: OrderNotFoundException: Cannot process PAYMENT_COMPLETED for Order #10023. Order does not exist!
FATAL: DuplicatePaymentException: Payment for Order #10023 was charged twice!
```

브로커 파티션의 실제 커밋된 오프셋 로그를 열어본 개발팀은 충격에 빠졌습니다:
```text
Offset 0: PAYMENT_COMPLETED   <-- 결제가 주문보다 먼저 기록됨! (순서 역전)
Offset 1: ORDER_CREATED       <-- 주문이 뒤늦게 기록됨!
Offset 2: PAYMENT_COMPLETED   <-- 결제가 한 번 더 기록됨! (중복 결제)
Offset 3: SHIPPING_REQUESTED
```

개발자들의 절규:
> "분명히 프로듀서 코드에서 단일 파티션으로 0번, 1번, 2번 순서대로 `send()`를 호출했는데, 왜 브로커 파티션에는 결제(Seq 1)가 주문(Seq 0)보다 먼저 저장되고 결제가 2번이나 중복 저장된 건가요?!"

범인은 바로 **프로듀서 파이프라이닝(`max.in.flight.requests.per.connection = 5`)과 재시도(`retries > 0`), 그리고 멱등성 비활성화(`enable.idempotence = false`)**의 조합이었습니다:
1. 프로듀서가 높은 처리량을 위해 Seq 0과 Seq 1을 동시에 네트워크 파이프에 밀어 넣었습니다.
2. Seq 0 패킷이 네트워크 지연으로 브로커에 늦게 도착하는 사이, 뒤따라가던 Seq 1 패킷이 브로커에 먼저 도착했습니다.
3. 브로커는 멱등성 검증 기능이 꺼져 있어 Seq 1을 Offset 0에 먼저 커밋해 버렸습니다!
4. Seq 0의 ACK가 늦어지자 프로듀서는 타임아웃으로 판단하고 Seq 0을 재전송하여 Offset 1에 뒤늦게 기록했습니다. (순서 역전!)
5. 게다가 Seq 1의 성공 ACK가 네트워크에서 유실되자 프로듀서가 Seq 1을 다시 보내어 Offset 2에 중복 저장되었습니다!

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 카프카 브로커의 **메시지 시퀀스 검증 및 멱등성 제어 메커니즘 (KIP-98)**을 시뮬레이션합니다.

### (1) 프로듀서 및 브로커 상태
- 프로듀서 멱등성 설정: `enable_idempotence` (`true` 또는 `false`)
- 브로커는 단일 파티션에 대해 다음에 도착해야 할 기대 시퀀스 번호 `expected_seq`를 0부터 시작하여 관리합니다.
- 브로커는 현재 파티션에 영구 커밋된 메시지 시퀀스 목록(`committed_seqs`)을 유지합니다.

### (2) 패킷 인입 시 브로커 동작 규칙

브로커에 시퀀스 번호 $K$를 가진 패킷이 도착했을 때:

#### 1) `enable_idempotence == true` (멱등성 활성화)
- **$K == expected\_seq$ (정상 순서 인입)**:
  - 브로커 파티션 로그에 정상 커밋합니다.
  - `expected_seq += 1`
- **$K < expected\_seq$ (중복 패킷 인입 - Duplicate Defense)**:
  - 이미 이전에 커밋된 메시지의 재전송이므로, **파티션 로그에 중복 기록하지 않고 폐기(Drop)**합니다.
  - `DUPLICATES_DROPPED += 1`
- **$K > expected\_seq$ (순서 역전 패킷 인입 - Out-of-Order Defense)**:
  - 중간 메시지가 아직 도착하지 않았으므로, **커밋을 단호히 거부하고 예외(`OutOfOrderSequenceException`)를 반환**합니다.
  - 파티션 로그에 기록되지 않습니다.
  - `OUT_OF_ORDER_REJECTIONS += 1`

#### 2) `enable_idempotence == false` (멱등성 비활성화)
- 브로커는 시퀀스 번호를 검증하지 않고 **도착하는 족족 파티션 로그에 무조건 커밋**합니다.
- 만약 $K$가 이미 로그에 커밋된 적이 있다면:
  - `DUPLICATES_COMMITTED += 1`
- 만약 $K$가 지금까지 커밋된 시퀀스 번호의 최댓값보다 작다면 (과거 메시지가 나중에 끼어듦):
  - `ORDER_INVERSIONS += 1`

---

## 3. 입력 형식

- 첫째 줄에 멱등성 활성화 여부 `enable_idempotence` (`true` 또는 `false`)가 주어집니다.
- 둘째 줄에 브로커에 도착하는 패킷 이벤트 개수 $M$ ($1 \le M \le 1,000$)이 주어집니다.
- 셋째 줄부터 $M$개 줄에 걸쳐 각 도착 패킷 정보가 공백으로 구분되어 주어집니다:
  - `seq msg_id` ($0 \le seq \le 10^9$, 문자열 $msg\_id$)

## 4. 출력 형식

- 첫째 줄에 다음 통계를 공백으로 구분하여 출력합니다:
  - `COMMITTED_COUNT: <수> DUPLICATES_COMMITTED: <수> DUPLICATES_DROPPED: <수> OUT_OF_ORDER_REJECTIONS: <수> ORDER_INVERSIONS: <수>`
- 둘째 줄에 최종 커밋된 시퀀스 번호 목록을 콤마(`,`)로 구분하여 출력합니다:
  - `FINAL_LOG_SEQS: <seq1,seq2,...>` (커밋된 메시지가 없으면 `FINAL_LOG_SEQS: EMPTY`)

---

## 5. 입출력 예제

### 예제 1 (`enable_idempotence = false`: 순서 역전 및 중복 커밋 발생)
#### 입력
```text
false
4
1 PAYMENT
0 ORDER
1 PAYMENT_RETRY
1 PAYMENT_DUP_ACK_LOST
```
#### 출력
```text
COMMITTED_COUNT: 4 DUPLICATES_COMMITTED: 2 DUPLICATES_DROPPED: 0 OUT_OF_ORDER_REJECTIONS: 0 ORDER_INVERSIONS: 1
FINAL_LOG_SEQS: 1,0,1,1
```

### 예제 2 (`enable_idempotence = true`: 완벽한 순서 보장 및 중복 제거)
#### 입력
```text
true
4
1 PAYMENT
0 ORDER
1 PAYMENT_RETRY
1 PAYMENT_DUP_ACK_LOST
```
#### 출력
```text
COMMITTED_COUNT: 2 DUPLICATES_COMMITTED: 0 DUPLICATES_DROPPED: 1 OUT_OF_ORDER_REJECTIONS: 1 ORDER_INVERSIONS: 0
FINAL_LOG_SEQS: 0,1
```
**비교 설명**:
- 멱등성이 꺼져 있을 때는 패킷 순서대로 `1, 0, 1, 1`이 다 커밋되어 중복 2건, 순서 역전 1건이 발생했습니다.
- 멱등성을 켜면 Seq 1이 먼저 왔을 때 거부(OUT_OF_ORDER_REJECTIONS = 1)되고, Seq 0이 먼저 커밋된 뒤 재시도된 Seq 1이 정상 커밋되며, 이후 중복 패킷은 드롭(DUPLICATES_DROPPED = 1)되어 최종 `0, 1`만 완벽히 남습니다.
