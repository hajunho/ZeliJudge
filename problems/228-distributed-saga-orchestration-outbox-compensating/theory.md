# 문제 228 이론: 분산 사가(Saga) 패턴과 트랜잭셔널 아웃박스(Transactional Outbox) 및 보상 트랜잭션 심층 분석

## 1. 분산 트랜잭션의 한계와 2PC vs Saga 비교

마이크로서비스 아키텍처(MSA)에서는 각 서비스가 독립적인 데이터베이스를 보유하는 Database-per-Service 원칙을 따릅니다. 이 환경에서 단일 ACID 트랜잭션은 불가능합니다.

```
[Two-Phase Commit (2PC) vs Saga Pattern]

Two-Phase Commit (2PC):
Coordinator ---> [Prepare?] ---> Node A (Locks Row)
Coordinator ---> [Prepare?] ---> Node B (Locks Row)
Coordinator ---> [Commit!]  ---> Node A / Node B (Release Locks)
-> Problems: Blocking protocol, Distributed Deadlocks, Latency explosion, Single Point of Failure!

Saga Pattern (Eventual Consistency):
Local Tx 1 (Order) -> Local Tx 2 (Inventory) -> Local Tx 3 (Payment)
If Tx 3 fails:
Trigger Compensating Tx 2' (Undo Inventory) -> Compensating Tx 1' (Cancel Order)
-> Benefits: Non-blocking, Local locks only, High throughput, Resilient to network partitions!
```

---

## 2. 코레오그래피(Choreography) vs 오케스트레이션(Orchestration)

| 비교 항목 | 코레오그래피 (Choreography) | 오케스트레이션 (Orchestration) |
| :--- | :--- | :--- |
| **제어 구조** | 탈중앙화 (Decentralized Pub/Sub) | 중앙 집중식 상태 머신 (Centralized Coordinator) |
| **서비스 결합도** | 느슨한 결합 (이벤트 브로커 의존) | 오케스트레이터가 하위 서비스 API 호출 |
| **복잡도 증가 시** | 스파게티 의존성, 순환 참조 위험 급증 | 워크플로우 로직이 단일 위치에 명확히 캡슐화 |
| **장애 추적성** | 분산 추적(Distributed Tracing) 난해 | 현재 사가 상태(State)와 진행 단계 즉시 조회 가능 |
| **권장 사용처** | 2~3개 이하의 단순 서비스 파이프라인 | 4개 이상의 복잡한 비즈니스 프로세스 및 금융 거래 |

---

## 3. 이중 쓰기(Dual-Write) 문제와 트랜잭셔널 아웃박스 패턴

마이크로서비스에서 로컬 DB 갱신과 메시지 브로커 발행을 동시에 수행할 때 필연적으로 발생하는 문제가 **Dual-Write Problem**입니다:

```
[The Dual-Write Problem]
try {
    db.commit(); // 1. DB Commit Success!
    kafka.send(event); // 2. Network timeout! Crash!
}
=> The database state changed, but the event was NEVER published!
=> Downstream services remain completely unaware -> Catastrophic Data Inconsistency!
```

### 3.1 트랜잭셔널 아웃박스(Transactional Outbox) 해결책
동일한 로컬 RDBMS 트랜잭션 내부에서 비즈니스 테이블과 **아웃박스 테이블(`outbox_table`)**에 메시지를 원자적(`BEGIN ... COMMIT`)으로 함께 저장합니다.

```sql
BEGIN TRANSACTION;
INSERT INTO orders (id, amount, status) VALUES ('ord-101', 50000, 'CREATED');
INSERT INTO outbox_table (aggregate_id, event_type, payload) VALUES ('ord-101', 'OrderCreated', '{...}');
COMMIT;
```

- **Debezium / CDC (Change Data Capture)**: 데이터베이스의 트랜잭션 로그(WAL, Binlog)를 직접 테일링하여 아웃박스 테이블에 기록된 이벤트를 Kafka로 100% 무손실 보장(At-Least-Once) 발행합니다.
- **멱등 수신자(Idempotent Consumer)**: 중복 발행 가능성에 대비하여 컨슈머는 고유 이벤트 ID(`message_id`) 기반 멱등 테이블을 통해 중복 처리를 완벽 차단합니다.

---

## 4. 보상 트랜잭션(Compensating Transaction) 설계 원칙

보상 트랜잭션은 데이터베이스의 물리적 `ROLLBACK`이 아니라, 비즈니스적 **의미론적 역연산(Semantic Undo)**입니다:
- 예: `차감된 계좌 잔액 5만 원` $\rightarrow$ `환불 5만 원 입금`.
- 예: `예약된 항공권 좌석` $\rightarrow$ `좌석 예약 취소`.

### 4.1 보상 트랜잭션의 3대 필수 속성
1. **멱등성 (Idempotency)**: 네트워크 재시도로 인해 동일한 취소 요청이 3회 전달되어도 환불이 1회만 실행되어야 합니다.
2. **가환성 (Commutativity)**: 전진 트랜잭션과 보상 트랜잭션의 도착 순서가 역전(Out-of-Order)되더라도 최종 상태가 정합성을 유지해야 합니다.
3. **무조건 성공 보장 (Must Ultimately Succeed)**:
   - 보상 트랜잭션은 비즈니스 검증 실패로 거부되어서는 안 됩니다.
   - 일시적 네트워크 장애 시 지수 백오프(Exponential Backoff)를 통해 재시도하며, 최대 재시도 초과 시 즉시 **데드 레터 큐(DLQ, Dead Letter Queue)**로 라우팅하고 긴급 엔지니어링 알림을 격발해야 합니다.
