# Problem 069: 분산 트랜잭션 듀얼 라이트의 저주와 트랜잭셔널 아웃박스 패턴 (Dual Write Problem & Transactional Outbox Pattern)

## 문제 설명

대규모 트래픽을 처리하는 이커머스 MSA(마이크로서비스 아키텍처) 팀에서 블랙 프라이데이 당일 심각한 분산 데이터 불일치 장애가 발생했습니다:
> "고객 통장에서는 분명히 돈이 빠져나갔고 주문 DB에도 '결제 완료'라고 적혀 있는데, 배송팀과 재고팀에는 아무런 메시지가 전달되지 않았습니다!  
> 고객은 돈만 내고 1주일째 물건을 받지 못해 고객센터에 항의가 빗발치고 있습니다. 카프카 브로커 로그를 확인해보니 일시적인 네트워크 순단(Network Glitch)으로 메시지 발행(`send()`)이 타임아웃 실패했습니다!"

원인은 데이터베이스 쓰기와 메시지 브로커 발행이라는 서로 다른 두 분산 저장소를 원자적 트랜잭션 없이 연속 호출한 **듀얼 라이트(Dual Write) 안티패턴**이었습니다:
- 주문 DB `INSERT` 성공 직후 카프카로 `OrderCreated` 이벤트를 쏘는 구조에서, 카프카 브로커가 배포 재기동 중이거나 네트워크가 순단되면 이벤트는 영구 유실됩니다.
- 이미 DB 커밋이 완료된 상태이므로 로컬 트랜잭션을 롤백할 수도 없습니다.
- 반대로 카프카에 먼저 메시지를 쏘고 DB 저장을 시도하면, DB 데드락이나 유니크 제약조건 위반 시 결제도 안 된 상품이 배송팀으로 전송되는 기업 파산 참사(Ghost Delivery)가 발생합니다.

이 문제를 우아하게 해결하는 분산 아키텍처의 표준 해법이 바로 **트랜잭셔널 아웃박스 패턴(Transactional Outbox Pattern)**입니다:
1. **원자적 로컬 커밋(Atomic Local Commit)**: 외부 브로커로 직접 네트워크 통신을 시도하지 않고, 주문 데이터와 발행할 이벤트를 **RDBMS의 동일한 단일 로컬 트랜잭션**으로 `orders` 테이블과 `outbox` 테이블에 함께 영속화합니다.
2. **비동기 메시지 릴레이(Message Relay Poller/CDC)**: 별도의 백그라운드 릴레이 프로세스가 Outbox 테이블을 주기적으로 읽어 브로커로 발행하며, 성공 시 `PUBLISHED`로 마킹합니다.
3. **무손실 회복 탄력성(Lossless Fault Tolerance)**: 브로커가 1시간 동안 다운되어도 이벤트는 DB에 안전하게 보존되며, 브로커 복구 즉시 순차 발행되어 **100% 무손실 전달(At-Least-Once Delivery)**을 달성합니다.

당신은 동일한 주문 스트림과 브로커 장애 상황에 대해 **Naive Dual Write 엔진**과 **Transactional Outbox 엔진**의 이벤트 발행 상태, 재시도/DLQ 처리, 유실률을 비교 시뮬레이션하는 신뢰성 엔지니어링 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `RELAY_BATCH_SIZE <batch_size>`: Outbox 릴레이 1회 실행 시 폴링할 최대 레코드 수.
- `MAX_RETRIES <max_retries>`: 브로커 장애 시 재시도 허용 횟수.

---

### 2. 두 가지 이벤트 발행 아키텍처

#### 1) Naive Dual Write Engine (안티패턴)
- 주문 요청(`PLACE_ORDER`) 발생 시:
  - 1단계: RDBMS `orders` 테이블에 주문 저장 (`DB_SAVED=YES`).
  - 2단계: 카프카 브로커로 즉시 발행 시도.
    - 브로커가 `UP`: 브로커 수신 큐에 메시지 적재 (`BROKER_PUBLISH:SUCCESS`).
    - 브로커가 `DOWN`: 네트워크 예외 발생! 발행 실패 및 이벤트 영구 유실 (`BROKER_PUBLISH:FAILED_LOST`).
- 릴레이 기능이 지원되지 않음 (`NO_RELAY_SUPPORT`).

#### 2) Transactional Outbox Engine (모범 설계)
- 주문 요청(`PLACE_ORDER`) 발생 시:
  - 단일 로컬 DB 트랜잭션으로 `orders` 테이블과 `outbox` 테이블에 동시 저장 (`DB_TX_COMMITTED=YES`).
  - 초기 Outbox 상태는 항상 `OUTBOX_STATUS:PENDING`, `retries=0`.
  - 외부 브로커 네트워크 통신을 동기 호출하지 않으므로 브로커 상태와 무관하게 100% 안전 커밋.
- 릴레이 실행(`RUN_RELAY`) 시:
  - `status == 'PENDING'`인 레코드를 등록 순서대로 최대 `RELAY_BATCH_SIZE`개 폴링.
  - 브로커가 `UP`: 각 레코드를 브로커 수신 큐로 전송하고 상태를 `PUBLISHED`로 변경.
  - 브로커가 `DOWN`: 전송 실패. 각 레코드의 `retries` 1 증가.
    - `retries >= MAX_RETRIES`에 도달한 레코드는 상태를 `FAILED_DLQ`로 격리.

---

### 3. 4대 액션 명세

#### 1) `BROKER_STATUS <UP | DOWN>`
- 카프카 브로커의 네트워크 상태 변경 (순단 및 복구 시뮬레이션).
- 출력 (1줄):
  ```text
  ACT <idx> BROKER_STATUS STATE:<UP|DOWN>
  ```

#### 2) `PLACE_ORDER <order_id> <user_id> <amount>`
- 주문 생성 이벤트.
- 출력 (3줄):
  ```text
  ACT <idx> PLACE_ORDER <order_id> USER:<user_id> AMT:<amount>
    NAIVE: DB_SAVED=YES BROKER_PUBLISH:<SUCCESS|FAILED_LOST>
    OUTBOX: DB_TX_COMMITTED=YES OUTBOX_STATUS:PENDING
  ```

#### 3) `RUN_RELAY`
- Outbox 릴레이 1회 폴링 배치 주기 실행.
- 출력 (3줄):
  ```text
  ACT <idx> RUN_RELAY
    NAIVE: NO_RELAY_SUPPORT
    OUTBOX: POLLED:<polled_cnt> PUBLISHED:<pub_cnt> RETRIED:<retry_cnt> FAILED_DLQ:<dlq_cnt> REMAINING_PENDING:<rem_cnt>
  ```

#### 4) `CHECK_CONSISTENCY`
- 현재 시점의 양 엔진 정합성 상태 점검.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_CONSISTENCY
    NAIVE: DB_ORDERS:<cnt> BROKER_RECEIVED:<cnt> LOST_EVENTS:<lost> STATUS:<INCONSISTENT|CONSISTENT>
    OUTBOX: DB_ORDERS:<cnt> BROKER_RECEIVED:<cnt> OUTBOX_PENDING:<p> STATUS:CONSISTENT
  ```
  - Naive 엔진은 `LOST_EVENTS > 0`이면 `INCONSISTENT`, `0`이면 `CONSISTENT`.
  - Outbox 엔진은 모든 주문이 브로커 또는 Outbox에 안전하게 영속되므로 항상 `CONSISTENT`.

---

## 입력 형식

```text
SYSTEM_CONFIG
RELAY_BATCH_SIZE <batch_size>
MAX_RETRIES <max_retries>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 출력 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (4줄):
```text
SUMMARY TOTAL_ORDERS:<total_orders>
SUMMARY NAIVE BROKER_RECEIVED:<cnt> LOST_EVENTS:<lost> (LOSS_RATE:<loss_pct:.2f>%)
SUMMARY OUTBOX BROKER_RECEIVED:<cnt> OUTBOX_PENDING:<p> OUTBOX_DLQ:<dlq> LOST_EVENTS:0 (LOSS_RATE:0.00%)
SUMMARY PATTERN_VERDICT: OUTBOX_100%_LOSSLESS
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
RELAY_BATCH_SIZE 2
MAX_RETRIES 3
ACTIONS
BROKER_STATUS UP
PLACE_ORDER ORD-1 user-A 10000
BROKER_STATUS DOWN
PLACE_ORDER ORD-2 user-B 20000
PLACE_ORDER ORD-3 user-C 30000
RUN_RELAY
BROKER_STATUS UP
RUN_RELAY
RUN_RELAY
CHECK_CONSISTENCY
```

**출력:**
```text
ACT 1 BROKER_STATUS STATE:UP
ACT 2 PLACE_ORDER ORD-1 USER:user-A AMT:10000
  NAIVE: DB_SAVED=YES BROKER_PUBLISH:SUCCESS
  OUTBOX: DB_TX_COMMITTED=YES OUTBOX_STATUS:PENDING
ACT 3 BROKER_STATUS STATE:DOWN
ACT 4 PLACE_ORDER ORD-2 USER:user-B AMT:20000
  NAIVE: DB_SAVED=YES BROKER_PUBLISH:FAILED_LOST
  OUTBOX: DB_TX_COMMITTED=YES OUTBOX_STATUS:PENDING
ACT 5 PLACE_ORDER ORD-3 USER:user-C AMT:30000
  NAIVE: DB_SAVED=YES BROKER_PUBLISH:FAILED_LOST
  OUTBOX: DB_TX_COMMITTED=YES OUTBOX_STATUS:PENDING
ACT 6 RUN_RELAY
  NAIVE: NO_RELAY_SUPPORT
  OUTBOX: POLLED:2 PUBLISHED:0 RETRIED:2 FAILED_DLQ:0 REMAINING_PENDING:3
ACT 7 BROKER_STATUS STATE:UP
ACT 8 RUN_RELAY
  NAIVE: NO_RELAY_SUPPORT
  OUTBOX: POLLED:2 PUBLISHED:2 RETRIED:0 FAILED_DLQ:0 REMAINING_PENDING:1
ACT 9 RUN_RELAY
  NAIVE: NO_RELAY_SUPPORT
  OUTBOX: POLLED:1 PUBLISHED:1 RETRIED:0 FAILED_DLQ:0 REMAINING_PENDING:0
ACT 10 CHECK_CONSISTENCY
  NAIVE: DB_ORDERS:3 BROKER_RECEIVED:1 LOST_EVENTS:2 STATUS:INCONSISTENT
  OUTBOX: DB_ORDERS:3 BROKER_RECEIVED:3 OUTBOX_PENDING:0 STATUS:CONSISTENT
SUMMARY TOTAL_ORDERS:3
SUMMARY NAIVE BROKER_RECEIVED:1 LOST_EVENTS:2 (LOSS_RATE:66.67%)
SUMMARY OUTBOX BROKER_RECEIVED:3 OUTBOX_PENDING:0 OUTBOX_DLQ:0 LOST_EVENTS:0 (LOSS_RATE:0.00%)
SUMMARY PATTERN_VERDICT: OUTBOX_100%_LOSSLESS
```
