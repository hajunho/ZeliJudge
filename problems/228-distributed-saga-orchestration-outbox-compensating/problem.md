# 문제 228: 분산 트랜잭션 사가(Saga) 패턴: 코레오그래피(Choreography) vs 오케스트레이션(Orchestration) & 보상 트랜잭션 실패와 트랜잭셔널 아웃박스 시뮬레이터

## 1. 개요 및 배경 (Incident Scenario)

대규모 글로벌 이커머스 마이크로서비스 아키텍처(MSA) 환경에서 주문(`Order`), 재고(`Inventory`), 결제(`Payment`), 배송(`Delivery`) 서비스 간의 트랜잭션 정합성 붕괴로 인해 수억 원 규모의 재고 불일치 및 유령 결제 사고가 발생했습니다.

기존 모놀리식 DB 환경에서는 RDBMS의 ACID 트랜잭션을 통해 완벽한 정합성을 유지했으나, 서비스별 독점 데이터베이스(Database-per-Service)로 분할된 후 전통적인 2단계 커밋(2PC, Two-Phase Commit)을 적용했을 때 분산 락(Distributed Lock) 경합으로 인해 초당 트랜잭션 처리량(TPS)이 90% 급감하는 성능 병목이 발생했습니다.

인프라 및 백엔드 팀은 분산 락을 해제하고 최종 일관성(Eventual Consistency)을 달성하기 위해 **사가 패턴(Saga Pattern)**을 도입했으나, 다음과 같은 심각한 설계 결함에 부딪혔습니다:

1. **코레오그래피(Choreography) 방식의 순환 이벤트 폭풍(Circular Event Storm)**:
   - 중앙 조율자 없이 서비스들이 Kafka 토픽을 통해 서로의 이벤트를 직접 발행·구독(Pub/Sub)하도록 구성했습니다. 그러나 서비스 수가 늘어나며 `Order` $\rightarrow$ `Inventory` $\rightarrow$ `Notification` $\rightarrow$ `Order`와 같은 순환 의존성(Circular Dependency)이 발생하여 이벤트가 무한 루프를 돌며 카프카 브로커를 다운시키는 순환 이벤트 폭풍(`CHOREOGRAPHY_CIRCULAR_EVENT_STORM`)이 터졌습니다.
2. **이중 쓰기(Dual-Write) 문제로 인한 이벤트 유실 및 유령 커밋**:
   - 로컬 DB에 데이터를 커밋한 직후 Kafka로 이벤트를 발행하는 일반적인 이중 쓰기(Dual-Write) 코드를 작성했으나, DB 커밋 직후 네트워크 순단이 발생하면 메시지 브로커로 이벤트가 전달되지 못했습니다. 그 결과 `Order`는 생성되었으나 후속 서비스(`Inventory`, `Payment`)는 이벤트를 영원히 수신하지 못해 유령 커밋 불일치(`DUAL_WRITE_MESSAGE_LOSS_INCONSISTENCY`)가 발생했습니다.
3. **보상 트랜잭션(Compensating Transaction) 재시도 고갈과 데이터 왜곡**:
   - 결제 서비스에서 한도 초과로 트랜잭션이 실패하여 이전 단계의 예약된 재고를 복구하는 보상 트랜잭션을 실행했으나, 재고 서비스의 일시적 장애로 인해 보상 요청이 최대 재시도 횟수(`max_compensation_retries`)를 초과하여 최종 실패했습니다. 그 결과 주문은 취소되었으나 재고는 영구 차감된 채 방치되는 데이터 불일치(`COMPENSATING_RETRY_EXHAUSTION_INCONSISTENCY`)가 고착화되었습니다.

엔지니어링 팀은 **중앙화된 사가 오케스트레이터(Saga Orchestrator State Machine)**, DB 로컬 트랜잭션과 원자적으로 결합되는 **트랜잭셔널 아웃박스 패턴(Transactional Outbox Pattern + CDC)**, 그리고 역방향 보상 롤백 메커니즘을 통합 구축하여 완벽한 분산 최종 일관성을 확보하기로 결정했습니다.

본 문제에서는 사가 실행 패턴, 아웃박스 활성화 여부, 결함 주입 및 보상 트랜잭션 재시도 조건에 따라 분산 트랜잭션의 상태 머신 전이를 시뮬레이션하고 최종 일관성을 판정하는 프로그램을 구현합니다.

---

## 2. 아키텍처 및 사가 패턴 비교

```
[1. Choreography Saga (Decentralized Pub/Sub Event Mesh)]
Order Svc ------(OrderCreated)-----> Inventory Svc
   ^                                        |
   |                                        v (InventoryReserved)
Notification Svc <---(PaymentFailed)--- Payment Svc
=> Danger: Spaghetti dependencies, Circular Event Storms, No central visibility!

---------------------------------------------------------------------------------

[2. Orchestrated Saga with Transactional Outbox Pattern (Recommended)]
               +----------------------------------+
               |    Saga Orchestrator Engine      |
               | (State Machine: ORDER_PENDING -> |
               |  INVENTORY_RESERVED -> COMPLETED)|
               +-----------------+----------------+
                                 | Command / Reply
         +-----------------------+-----------------------+
         |                       |                       |
         v                       v                       v
   [Order Svc]             [Inventory Svc]         [Payment Svc]
   +-------------+         +-------------+         +-------------+
   | Local DB    |         | Local DB    |         | Local DB    |
   | Outbox Table|         | Outbox Table|         | Outbox Table|
   +-------------+         +-------------+         +-------------+
         | (CDC)                 | (CDC)                 | (CDC)
   ======v=======================v=======================v========
                      Apache Kafka / Event Bus
```

---

## 3. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "saga_pattern": "ORCHESTRATION",
    "outbox_pattern_enabled": true,
    "max_compensation_retries": 3
  },
  "transaction": {
    "order_id": "ord-101",
    "steps": [
      {"service": "ORDER"},
      {"service": "INVENTORY"},
      {"service": "PAYMENT"},
      {"service": "DELIVERY"}
    ],
    "injected_failures": {
      "PAYMENT": "INSUFFICIENT_FUNDS",
      "INVENTORY_COMPENSATION_RETRIES": 1
    },
    "network_failure_step": null
  }
}
```

- `config`:
  - `saga_pattern`: `"ORCHESTRATION"` 또는 `"CHOREOGRAPHY"`
  - `outbox_pattern_enabled`: 트랜잭셔널 아웃박스 패턴 활성화 여부 (boolean)
  - `max_compensation_retries`: 보상 트랜잭션 최대 재시도 허용 횟수 (기본 3)
- `transaction`:
  - `order_id`: 트랜잭션 식별자
  - `steps`: 실행할 순차 서비스 단계 목록 (`[{"service": "SERVICE_NAME"}, ...]`)
  - `injected_failures`: 결함 주입 맵
    - `SERVICE_NAME`: 해당 서비스의 전진 트랜잭션 실패 사유
    - `SERVICE_NAME_COMPENSATION_RETRIES`: 해당 서비스의 역방향 보상 트랜잭션 실패 재시도 횟수
  - `network_failure_step`: 이중 쓰기(Dual-Write) 네트워크 결함이 발생하는 서비스명 (문자열 또는 `null`)

---

## 4. 연산 및 상태 머신 전이 규칙

1. **코레오그래피 검증 (CHOREOGRAPHY)**:
   - 단계 목록(`steps`) 내에 이미 방문한 서비스가 다시 등장하는 순환 의존성이 존재하거나, 서비스 단계 수가 5개 이상으로 복잡도가 높은 경우:
     - `status`: `"FAILED"`
     - `verdict`: `"CHOREOGRAPHY_CIRCULAR_EVENT_STORM"`
     - `final_state`: `"CIRCULAR_STORM"`
2. **이중 쓰기 결함 검증 (Dual-Write Failure)**:
   - `outbox_pattern_enabled == False`이고, 현재 서비스가 `network_failure_step`과 일치하는 경우:
     - DB에는 커밋되었으나 브로커로의 메시지 발행이 유실되어 후속 서비스가 기아 상태에 빠짐:
     - `status`: `"FAILED"`
     - `verdict`: `"DUAL_WRITE_MESSAGE_LOSS_INCONSISTENCY"`
     - `final_state`: `"GHOST_COMMITTED_STATE"`
3. **전진 트랜잭션 실행 (Forward Execution)**:
   - 각 단계를 순차 실행하며 정상 완료된 서비스를 `completed_steps`에 기록.
   - `injected_failures`에 포함된 서비스를 만나면 전진 실행을 즉시 중단하고 역방향 보상 단계로 진입.
4. **역방향 보상 트랜잭션 실행 (Compensating Rollback)**:
   - 완료된 서비스(`completed_steps`)들을 **역순(Reverse Order)**으로 순회하며 보상 트랜잭션 실행.
   - 각 서비스에 대해 `SERVICE_COMPENSATION_RETRIES`를 확인:
     - 재시도 횟수 $\le \text{max\_compensation\_retries}$ 이면 보상 성공 (`compensated_steps`에 추가).
     - 재시도 횟수 $> \text{max\_compensation\_retries}$ 이면 보상 실패 (`uncompensated_services`에 추가, `compensation_failed = True`).
   - 보상 실패가 1건이라도 발생하면:
     - `status`: `"FAILED"`
     - `verdict`: `"COMPENSATING_RETRY_EXHAUSTION_INCONSISTENCY"`
     - `final_state`: `"PARTIALLY_COMPENSATED_DRIFT"`
   - 모든 보상이 정상 완료되면:
     - `status`: `"SUCCESS"`
     - `verdict`: `"SAGA_COMPENSATED_ROLLBACK_SUCCESS"`
     - `final_state`: `"SAFELY_COMPENSATED"`
5. **모든 전진 트랜잭션 성공 시**:
   - `status`: `"SUCCESS"`
   - `verdict`:
     - 코레오그래피 단순 성공 시: `"CHOREOGRAPHY_SIMPLE_SAGA_SUCCESS"`
     - 오케스트레이션 성공 시: `"OPTIMAL_ORCHESTRATED_SAGA_EVENTUAL_CONSISTENCY"`
   - `final_state`: `"COMMITTED"`

---

## 5. 진단 판정 (Verdict Rules) 요약

| 상태 (`status`) | 진단 결과 (`verdict`) | 발생 원인 |
| :--- | :--- | :--- |
| `FAILED` | `CHOREOGRAPHY_CIRCULAR_EVENT_STORM` | 코레오그래피 패턴에서 순환 의존성 또는 과도한 서비스 결합 발생 |
| `FAILED` | `DUAL_WRITE_MESSAGE_LOSS_INCONSISTENCY` | 아웃박스 미적용 상태에서 DB 커밋 후 네트워크 단절로 이벤트 유실 |
| `FAILED` | `COMPENSATING_RETRY_EXHAUSTION_INCONSISTENCY` | 롤백 보상 트랜잭션이 최대 재시도 횟수를 초과하여 영구 불일치 |
| `SUCCESS` | `SAGA_COMPENSATED_ROLLBACK_SUCCESS` | 장애 발생 후 역순 보상 트랜잭션이 100% 성공하여 안전하게 원복 |
| `SUCCESS` | `OPTIMAL_ORCHESTRATED_SAGA_EVENTUAL_CONSISTENCY` | 오케스트레이터 및 아웃박스 기반 전진 트랜잭션 100% 완료 |
| `SUCCESS` | `CHOREOGRAPHY_SIMPLE_SAGA_SUCCESS` | 단순 2~3단계 코레오그래피 사가 정상 완료 |

---

## 6. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_ORCHESTRATED_SAGA_EVENTUAL_CONSISTENCY",
  "metrics": {
    "saga_pattern": "ORCHESTRATION",
    "completed_steps": ["ORDER", "INVENTORY", "PAYMENT", "DELIVERY"],
    "compensated_steps": [],
    "uncompensated_services": [],
    "dual_write_loss": false,
    "final_state": "COMMITTED"
  }
}
```
