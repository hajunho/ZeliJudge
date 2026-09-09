# Problem 062: 분산 트랜잭션의 2PC 블로킹 지옥과 Saga 보상 트랜잭션 (Two-Phase Commit vs Saga Pattern)

## 문제 설명

모놀리식 서비스를 마이크로서비스 아키텍처(MSA)로 전환한 당신의 쇼핑몰 팀에서 대형 장애가 터졌습니다:
> "결제 서버 한 대가 네트워크 순단으로 잠시 응답하지 못했을 뿐인데,  
> 메인 쇼핑몰의 모든 상품 재고와 사용자 계좌가 꽁꽁 얼어붙어 전사 결제가 30분 동안 마비되었습니다!"

원인을 분석해보니, 과거 단일 DB 시절의 습관대로 분산 트랜잭션에 **2PC(Two-Phase Commit)**를 적용한 것이 화근이었습니다.
- 2PC 코디네이터가 Phase 1(Prepare)에서 재고와 잔액에 DB Row Lock을 걸어둔 뒤, Phase 2 직전에 장애로 멈춰버렸습니다.
- 참여자 노드들은 커밋할 수도, 롤백할 수도 없는 **Indoubt 상태**에 빠져 락을 풀지 못했고,
- 뒤이어 유입된 수천 명의 정상 고객들이 해당 상품과 계좌에 접근하려다 줄줄이 **Lock Wait Timeout**으로 폭사한 것입니다!

당신은 분산 환경의 표준인 **Saga 패턴(Orchestrated Saga Pattern with Compensating Transactions)**을 도입하여, 분산 락을 일체 걸지 않고 즉시 로컬 커밋하며 실패 시 **보상 트랜잭션(Semantic Rollback)**으로 최종 일관성을 달성하는 아키텍처를 구축해야 합니다.

동일한 트랜잭션 및 장애 시퀀스에 대해 **2PC**와 **Saga 패턴**을 동시에 시뮬레이션하고 자원 상태와 가용성을 비교 분석하는 엔진을 작성하세요.

---

## 시스템 요구사항 및 동작 규칙

### 1. 트랜잭션 구성
각 트랜잭션은 3단계로 이루어집니다:
1. `ORDER`: 주문 생성 (Order DB)
2. `STOCK`: 재고 차감 `qty` (Inventory DB)
3. `PAY`: 잔액 차감 `amount` (Payment DB)

### 2. 주입 가능한 장애 (Fault Types)
- `NONE`: 정상 실행.
- `OUT_OF_STOCK`: 가용 재고 부족으로 인한 실패.
- `INSUFFICIENT_FUNDS`: 계좌 잔액 부족으로 인한 실패.
- `PAYMENT_FAIL`: 외부 PG사/결제 게이트웨이 통신 실패.
- `CRASH_COORD_P2`: 2PC 코디네이터가 Phase 1 투표 완료 직후, Phase 2 전송 직전에 크래시됨!

---

### 3. 2PC (Two-Phase Commit) 동작 규칙
- **락 검사**:
  - 만약 해당 `item_id` 또는 `user_id`가 앞선 트랜잭션의 `CRASH_COORD_P2`로 인해 영구 블로킹(Indoubt)된 상태라면:
    - 락 획득 실패로 즉시 타임아웃 발생: `LOCK_TIMEOUT_BLOCKED(by=<blocker_tx_id>)` (락 타임아웃 카운트 +1).
- **Phase 1 (Prepare)**:
  - 락을 획득하고 각 참여자에게 투표 요청.
  - 재고 부족(`OUT_OF_STOCK`), 잔액 부족(`INSUFFICIENT_FUNDS`), 결제 실패(`PAYMENT_FAIL`) 중 하나라도 발생하면:
    - Phase 2 Global Abort 실행: 락 해제, `ABORTED(reason=<reason>)` (어보트 카운트 +1).
- **Phase 2 (Commit or Crash)**:
  - 만약 `fault == 'CRASH_COORD_P2'`:
    - 코디네이터 사망! 참여자들은 결정을 내리지 못하고 Indoubt 상태로 락을 영구 홀딩합니다!
    - 해당 `item_id`와 `user_id`는 이후 다른 트랜잭션에서 접근할 수 없도록 동결되며, 자원도 잠깁니다.
    - 상태: `BLOCKED_INDOUBT(CRASH_COORD_P2)` (블로킹 카운트 +1).
  - 정상인 경우 (`fault == 'NONE'`):
    - Global Commit 실행: 재고 차감, 잔액 차감, 락 해제.
    - 상태: `COMMITTED` (커밋 카운트 +1).

---

### 4. Saga 패턴 (보상 트랜잭션) 동작 규칙
- **분산 락 없음**: 어떤 경우에도 다른 트랜잭션을 막는 분산 락을 걸지 않습니다 (`BLOCKED:0`, `LOCK_TIMEOUTS:0`).
- **단계별 로컬 커밋 및 보상 트랜잭션**:
  - **Step 1 (T_ORDER)**: 주문 생성 (항상 성공, 로컬 커밋).
  - **Step 2 (T_STOCK)**: 재고 차감 시도.
    - 재고 부족 시: 보상 트랜잭션 `C_ORDER`(주문 취소) 실행 후 종료.
    - 상태: `COMPENSATED(failed_at=STOCK,reason=OUT_OF_STOCK)` (보상 카운트 +1).
    - 재고 충분 시: 재고 차감 후 로컬 커밋 (락 즉시 해제).
  - **Step 3 (T_PAY)**: 결제 시도.
    - 잔액 부족 또는 `PAYMENT_FAIL` 발생 시:
      - 역순 보상 트랜잭션 실행: `C_STOCK`(차감했던 재고 원복 `+qty`), `C_ORDER`(주문 취소).
      - 상태: `COMPENSATED(failed_at=PAY,reason=<reason>)` (보상 카운트 +1).
    - 결제 성공 시:
      - 잔액 차감 후 로컬 커밋 (락 즉시 해제).
      - 만약 `fault == 'CRASH_COORD_P2'`:
        - 오케스트레이터가 재부팅된 후 Saga 상태 로그(Outbox)를 통해 정상 완료를 확인하고 복구 커밋을 달성합니다.
        - 상태: `COMMITTED(RECOVERED)` (커밋 카운트 +1).
      - 정상 성공 시:
        - 상태: `COMMITTED` (커밋 카운트 +1).

---

## 입력 형식

```text
INIT_STOCKS
<item_id> <quantity>
...
INIT_BALANCES
<user_id> <balance>
...
TRANSACTIONS
<tx_id> <user_id> <item_id> <qty> <amount> <fault>
...
```

---

## 출력 형식

각 트랜잭션마다 1줄씩 다음 형식으로 출력합니다:
```text
TX <tx_id> 2PC:<2pc_status> SAGA:<saga_status>
```

모든 트랜잭션 처리가 끝난 후, 요약 6줄을 출력합니다 (아이템과 유저 목록은 알파벳 오름차순 정렬):
```text
SUMMARY 2PC COMMITTED:<cnt> ABORTED:<cnt> BLOCKED:<cnt> LOCK_TIMEOUTS:<cnt>
SUMMARY SAGA COMMITTED:<cnt> COMPENSATED:<cnt> BLOCKED:0 LOCK_TIMEOUTS:0
RESOURCE 2PC FINAL_STOCKS <item_1>:<qty> <item_2>:<qty> ...
RESOURCE 2PC FINAL_BALANCES <user_1>:<bal> <user_2>:<bal> ...
RESOURCE SAGA FINAL_STOCKS <item_1>:<qty> <item_2>:<qty> ...
RESOURCE SAGA FINAL_BALANCES <user_1>:<bal> <user_2>:<bal> ...
```

---

## 입출력 예시

### 예시 1: 코디네이터 크래시와 연쇄 락 블로킹

**입력:**
```text
INIT_STOCKS
item-A 10
item-B 5
INIT_BALANCES
user-1 100000
user-2 50000
TRANSACTIONS
TX_1 user-1 item-A 1 10000 CRASH_COORD_P2
TX_2 user-2 item-A 1 10000 NONE
TX_3 user-1 item-B 1 5000 NONE
TX_4 user-2 item-B 2 10000 NONE
```

**출력:**
```text
TX TX_1 2PC:BLOCKED_INDOUBT(CRASH_COORD_P2) SAGA:COMMITTED(RECOVERED)
TX TX_2 2PC:LOCK_TIMEOUT_BLOCKED(by=TX_1) SAGA:COMMITTED
TX TX_3 2PC:LOCK_TIMEOUT_BLOCKED(by=TX_1) SAGA:COMMITTED
TX TX_4 2PC:COMMITTED SAGA:COMMITTED
SUMMARY 2PC COMMITTED:1 ABORTED:0 BLOCKED:1 LOCK_TIMEOUTS:2
SUMMARY SAGA COMMITTED:4 COMPENSATED:0 BLOCKED:0 LOCK_TIMEOUTS:0
RESOURCE 2PC FINAL_STOCKS item-A:9 item-B:3
RESOURCE 2PC FINAL_BALANCES user-1:90000 user-2:40000
RESOURCE SAGA FINAL_STOCKS item-A:8 item-B:2
RESOURCE SAGA FINAL_BALANCES user-1:85000 user-2:30000
```

**설명:**
- `TX_1`에서 코디네이터가 크래시되어 2PC는 `item-A`와 `user-1`의 락을 영구 홀딩하는 `BLOCKED_INDOUBT`에 빠졌습니다.
- 그 결과 `TX_2`(item-A 구매 시도)와 `TX_3`(user-1 구매 시도)가 2PC에서 `LOCK_TIMEOUT_BLOCKED`로 줄줄이 폭사했습니다.
- 반면 Saga는 분산 락을 쓰지 않으므로 `TX_1`은 복구 완료(`RECOVERED`)되고, `TX_2`, `TX_3`, `TX_4` 모두 100% 정상 커밋되었습니다!
