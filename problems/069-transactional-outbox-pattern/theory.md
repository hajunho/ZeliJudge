# 분산 트랜잭션 듀얼 라이트의 저주와 트랜잭셔널 아웃박스 패턴 (Dual Write Problem & Transactional Outbox Pattern)

> **"DB에는 결제 완료라고 적혔는데, 왜 배송팀 카프카에는 메시지가 안 갔을까요?!"**  
> **"가계부 적고 우체국 가다 넘어진 비극 vs 가계부 속 우편함(Outbox)의 기적"**

---

## 1. 현실 세계 비유: 송금 장부와 우체국 편지의 엇갈림

철수에게 빌린 돈 10만 원을 갚기 위해 가계부를 정리하고 영수증 편지를 보내야 하는 상황을 상상해 봅시다.

```
[비극 A: 장부 먼저 적기 (DB Write -> Message Publish)]
1. 영희는 가계부에 "철수에게 10만 원 송금 완료"라고 펜으로 썼습니다 (DB Commit 성공).
2. 영수증 편지를 부치러 우체국에 가던 중 돌부리에 걸려 넘어져 편지가 하수구에 빠졌습니다 (Kafka 타임아웃).
3. 결과: 영희의 가계부에는 돈이 나간 것으로 적혀 있지만, 철수는 편지를 못 받아 물건을 안 보냅니다!
```

```
[비극 B: 편지 먼저 부치기 (Message Publish -> DB Write)]
1. 영희는 우체국에 먼저 가서 철수에게 "10만 원 송금했으니 물건 보내줘" 편지를 부쳤습니다 (Kafka Publish 성공).
2. 집에 돌아와 가계부에 적으려는데 볼펜 잉크가 터져 가계부가 찢어졌습니다 (DB Constraint 에러로 롤백).
3. 결과: 철수는 편지를 받고 물건을 보냈는데, 영희의 통장에서는 돈이 빠져나가지 않았습니다 (무료 배송 참사)!
```

서로 다른 두 공간(가계부와 우체국)에 동시에 똑같이 기록을 남기는 것은 불가능합니다. 이것이 바로 분산 시스템 엔지니어링의 오랜 숙적인 **'듀얼 라이트(Dual Write) 문제'**입니다.

---

## 2. 실무에서 만나는 듀얼 라이트의 저주 (The Dual Write Curse)

현대 마이크로서비스 아키텍처(MSA)에서는 이벤트 주도 아키텍처(EDA)를 위해 관계형 데이터베이스(RDBMS)와 메시지 브로커(Apache Kafka, RabbitMQ)를 함께 사용합니다:

```python
# ❌ 실무에서 흔히 저지르는 치명적 안티패턴
@transactional
def place_order(order_data):
    order = order_repository.save(order_data)  # 1. DB 쓰기 (로컬 트랜잭션)
    kafka_producer.send("order-created", order) # 2. 카프카 메시지 발행 (외부 네트워크 I/O)
```

무엇이 문제일까요?
1. **RDBMS와 Kafka는 같은 트랜잭션 매니저를 공유하지 않습니다.**
2. 1번(DB)이 커밋된 직후, 카프카 브로커에 일시적 네트워크 장애(Glitch)나 배포 재기동이 발생하면 2번은 예외(`TimeoutException`)를 던집니다.
3. 이미 DB 트랜잭션은 커밋 완료되었으므로 롤백할 수 없습니다!
4. **결과**: 고객의 돈은 결제되었으나 배송 준비, 재고 차감, 알림 발송 컨슈머는 이벤트를 영영 받지 못해 **'유령 주문(Ghost Order)'**으로 방치됩니다.

---

## 3. 구원투수: 트랜잭셔널 아웃박스 패턴 (Transactional Outbox Pattern)

이 문제를 해결하는 유일하게 신뢰할 수 있는 방법은 **"외부로 보낼 메시지도 비즈니스 데이터와 같은 DB 테이블 안에 한 번에 쑤셔 넣는 것"**입니다!

```
[RDBMS: 단일 로컬 트랜잭션 (ACID 100% 보장)]
┌────────────────────────────────────────────────────────┐
│ BEGIN TRANSACTION;                                     │
│   INSERT INTO orders (id, user, amount) VALUES (...);  │
│   INSERT INTO outbox (id, event_type, payload, status) │
│               VALUES (..., 'OrderCreated', ..., 'PENDING');
│ COMMIT;                                                │
└────────────────────────────────────────────────────────┘
                          │ (데이터 영속화 완료)
                          ▼
             [Outbox Message Relay / Poller]
                          │ (주기적 폴링 또는 DB WAL CDC 감지)
                          ▼
                  [Apache Kafka Topic]
                          │
                          ▼ (ACK 수신)
             [Outbox 상태를 'PUBLISHED'로 갱신]
```

### 핵심 메커니즘 3단계
1. **원자적 로컬 저장 (Atomic Local Commit)**:
   - 주문 데이터(`orders`)와 발행할 이벤트(`outbox`)를 **하나의 RDBMS 트랜잭션**으로 묶어 커밋합니다.
   - 둘 다 성공하거나 둘 다 실패하므로, DB 데이터와 Outbox 이벤트의 불일치가 수학적으로 0%입니다.
2. **비동기 메시지 릴레이 (Message Relay / Poller / CDC)**:
   - 별도의 백그라운드 워커(릴레이 프로세스 또는 Debezium CDC)가 Outbox 테이블에서 `PENDING` 상태의 레코드를 읽어 카프카로 전송합니다.
3. **상태 완료 마킹 및 At-Least-Once 보장**:
   - 카프카 브로커로부터 성공 응답(`ACK`)을 받으면 Outbox 레코드를 `PUBLISHED`로 마킹하거나 삭제합니다.
   - 브로커가 1시간 동안 죽어 있어도 이벤트는 DB Outbox 테이블에 안전하게 보존되며, 브로커가 살아나는 즉시 재전송되어 **단 1건의 유실도 없는 100% 전달(At-Least-Once Delivery)**을 달성합니다.

---

## 4. 메시지 릴레이 방식 비교: Polling vs CDC

| 비교 항목 | 1. 폴링 퍼블리셔 (Polling Publisher) | 2. 트랜잭션 로그 테일링 (CDC, Debezium) |
| :--- | :--- | :--- |
| **원리** | `SELECT * FROM outbox WHERE status = 'PENDING' LIMIT 100` 주기적 실행 | MySQL binlog, PostgreSQL WAL 등 DB 트랜잭션 로그를 직접 감지 |
| **구현 난이도** | 쉬움 (스케줄러 코드 몇 줄로 구현 가능) | 보통~높음 (Kafka Connect, Debezium 인프라 구성 필요) |
| **DB 부하** | 주기적 인덱스 스캔 부하 발생 | DB 로그를 스트리밍하므로 DB 쿼리 부하가 거의 없음 |
| **지연 시간 (Latency)** | 폴링 주기(예: 500ms ~ 1초)에 종속적 | 실시간(수 밀리초 단위 즉각 감지) |
| **적합한 환경** | 중소규모 서비스, 빠른 도입 필요 시 | 대규모 엔터프라이즈 초당 수만 건 트래픽 |

---

## 5. 컨슈머의 필수 요건: 멱등성 (Idempotency)

Outbox 패턴은 네트워크 재전송 시 동일한 메시지가 2번 이상 발행될 수 있는 **At-Least-Once(최소 1회 전송)** 모델입니다.  
따라서 메시지를 수신하는 다운스트림 컨슈머는 반드시 **Message ID를 활용한 중복 제거(Idempotent Consumer)** 로직을 갖추어야만 완벽한 시스템이 완성됩니다.

> **"네트워크 건너편의 브로커를 트랜잭션에 끌어들이지 마라. DB의 품 안에서 이벤트를 품고 우체부에게 맡겨라."**  
> 이것이 마이크로서비스 분산 트랜잭션을 설계하는 시니어 아키텍트의 불변의 원칙입니다.
