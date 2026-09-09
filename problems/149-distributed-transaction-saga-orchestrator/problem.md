# [주문은 들어갔는데 결제에서 에러 났더니 돈만 날아가고 배송은 안 와요?!: 분산 트랜잭션 사가 패턴(Saga Pattern)과 오케스트레이션(Orchestration) & 보상 트랜잭션(Compensating Transaction)]

## 1. 장애 시나리오: "재고 선점에 실패했는데 고객 카드 승인은 완료되어 돈만 빠져나간 결제 사고"

모놀리식 서비스를 마이크로서비스 아키텍처(MSA)로 전환한 이커머스 기업에서 데이터베이스를 서비스별로 완전히 물리적으로 분리했습니다:
- 주문 서비스 (`orders_db`)
- 결제 서비스 (`payments_db`)
- 재고 서비스 (`inventory_db`)
- 배송 서비스 (`delivery_db`)

단일 RDBMS 환경에서는 `@Transactional` 하나로 모든 테이블의 변경을 원자적(ACID)으로 커밋하거나 롤백할 수 있었습니다.
하지만 서비스와 DB가 네트워크로 쪼개진 MSA 환경에서 첫 대규모 프로모션이 열리자마자 **치명적인 정산 불일치 사고**가 폭발했습니다:

1. **주문 서비스**: 주문서 생성 성공 (`orders_db` 커밋)
2. **결제 서비스**: PG사 카드 10만 원 승인 완료 (`payments_db` 커밋)
3. **재고 서비스**: 앗! 하필 그 순간 마지막 재고가 소진되어 **재고 차감 실패 (`OutOfStockException`)**!
4. **결과**: 재고 서비스에서 에러가 났지만, 이미 각자 커밋을 끝낸 주문과 결제 서비스는 이 사실을 모른 채 끝났습니다.
   - **고객 계좌에서는 돈이 빠져나갔는데, 주문은 취소되지도 않고 배송도 영원히 오지 않는 최악의 결제 사고**가 터진 것입니다!

CS 센터와 재무팀의 비명:
> "분산 환경이라고 트랜잭션 롤백이 안 된다니요?! 카드 승인된 돈은 누가 환불해 주고, 생성된 유령 주문서는 누가 취소하나요?!"

아키텍트의 처방:
> "MSA에서는 전통적인 2PC(Two-Phase Commit)의 성능 저하와 락 블로킹을 피하기 위해, 로컬 트랜잭션을 체인으로 엮고 실패 시 역순으로 되돌리는 **사가 패턴(Saga Pattern)**과 **보상 트랜잭션(Compensating Transaction)**을 구현해야 합니다!"

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 중앙 집중식 **사가 오케스트레이터(Saga Orchestrator)** 기반의 분산 트랜잭션 실행 및 롤백 제어를 시뮬레이션합니다.

### (1) 사가 체인 및 서비스 구조
- 비즈니스 트랜잭션을 구성하는 $K$개의 순차적 서비스 목록이 주어집니다:
  $$S_1 	o S_2 	o \dots 	o S_K$$
- 각 서비스 $S_i$는 전진 로컬 트랜잭션 $T_i$와, 장애 시 이를 취소하는 **보상 트랜잭션(Compensating Transaction) $C_i$**를 갖습니다:
  - 예: $T_{payment}$ (카드 승인) $\leftrightarrow C_{payment}$ (카드 승인 취소/환불)
  - 예: $T_{order}$ (주문 생성) $\leftrightarrow C_{order}$ (주문 상태 CANCELLED 변경)

### (2) 오케스트레이터 실행 규칙
1. 오케스트레이터는 $S_1$부터 $S_K$까지 순서대로 명령을 전송하고 응답을 받습니다.
   - 오케스트레이터가 서비스로 실행 명령을 보낼 때 1회, 서비스가 응답을 회신할 때 1회의 메시지 통신이 발생합니다 (단계당 메시지 수 2회).
2. **정상 완료 (All Success)**:
   - 모든 $K$개 서비스가 `SUCCESS`를 반환하면:
   - 해당 사가는 영구 확정됩니다 (`COMMITTED_SAGAS += 1`).
3. **장애 발생 및 보상 트랜잭션 역순 실행 (Failure & Compensation)**:
   - 어떤 서비스 $S_m$ ($1 \le m \le K$)에서 `FAIL`이 발생하면:
   - 오케스트레이터는 즉시 전진 진행을 중단합니다.
   - 이미 성공적으로 커밋되었던 이전 단계들($S_{m-1}, S_{m-2}, \dots, S_1$)에 대해 **정확히 역순(Reverse Order)으로 보상 트랜잭션 $C_{m-1}, C_{m-2}, \dots, C_1$을 순차 호출**합니다.
   - 각 보상 트랜잭션 호출 역시 명령 1회 + 응답 1회로 총 2회의 메시지 통신이 발생합니다.
   - 각 보상 트랜잭션 실행 시마다 `TOTAL_COMPENSATIONS += 1`이 누적됩니다.
   - 해당 사가는 취소 처리됩니다 (`COMPENSATED_SAGAS += 1`).
   - (단, 첫 번째 서비스 $S_1$에서 곧바로 실패한 경우 실행된 선행 단계가 없으므로 보상 트랜잭션은 0회 실행됩니다.)

---

## 3. 입력 형식

- 첫째 줄에 서비스 개수 $K$ ($1 \le K \le 10$)가 주어집니다.
- 둘째 줄에 $K$개의 서비스 이름이 실행 순서대로 공백으로 구분되어 주어집니다:
  - 예: `ORDER PAYMENT INVENTORY DELIVERY`
- 셋째 줄에 처리할 사가 요청의 개수 $N$ ($1 \le N \le 1,000$)이 주어집니다.
- 넷째 줄부터 $N$개 줄에 걸쳐 각 사가의 정보가 주어집니다:
  - `saga_id status_1 status_2 ... status_K`
  - 각 $status_i$는 `SUCCESS` 또는 `FAIL`

## 4. 출력 형식

- 첫째 줄에 다음 통계를 공백으로 구분하여 출력합니다:
  - `COMMITTED_SAGAS: <n> COMPENSATED_SAGAS: <n> TOTAL_COMPENSATIONS: <n> TOTAL_MESSAGES: <n>`
- 둘째 줄에 가장 마지막으로 실패하여 보상 트랜잭션을 실행한 사가의 **보상 실행 서비스 순서(역순)**를 콤마(`,`)로 구분하여 출력합니다:
  - `LAST_COMPENSATED_ORDER: <S_prev,...,S_1>` (보상 실행된 사가가 없거나 보상 단계가 0개였다면 `LAST_COMPENSATED_ORDER: NONE`)

---

## 5. 입출력 예제

### 예제 1
#### 입력
```text
4
ORDER PAYMENT INVENTORY DELIVERY
2
saga1 SUCCESS SUCCESS SUCCESS SUCCESS
saga2 SUCCESS SUCCESS FAIL SUCCESS
```
#### 출력
```text
COMMITTED_SAGAS: 1 COMPENSATED_SAGAS: 1 TOTAL_COMPENSATIONS: 2 TOTAL_MESSAGES: 18
LAST_COMPENSATED_ORDER: PAYMENT,ORDER
```
**설명**:
- `saga1`: 4단계 모두 성공 $	o$ 메시지 $4 	imes 2 = 8$건, 커밋 성공.
- `saga2`: ORDER(성공), PAYMENT(성공), INVENTORY(실패!) $	o$ 전진 메시지 $3 	imes 2 = 6$건.
  - PAYMENT와 ORDER에 대해 역순으로 보상 트랜잭션 실행: `PAYMENT` $	o$ `ORDER` (보상 2회, 메시지 $2 	imes 2 = 4$건).
  - 총 메시지 = $8 + 6 + 4 = 18$건.
  - 마지막 보상 실행 순서는 `PAYMENT,ORDER`.
