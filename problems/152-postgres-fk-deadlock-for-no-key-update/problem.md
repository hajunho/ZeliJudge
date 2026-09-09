# #152 부모 테이블 행 하나 잠갔을 뿐인데 왜 자식 테이블 INSERT가 데드락으로 폭사해요?!: PostgreSQL 외래키(FK) 검사와 FOR UPDATE vs FOR NO KEY UPDATE 락 매트릭스 (PostgreSQL Foreign Key Deadlock & FOR NO KEY UPDATE)

## 1. 실무 장애 시나리오: "주문 상태를 변경했을 뿐인데 결제 영수증 저장이 데드락으로 터져요?!"

글로벌 결제 플랫폼 '젤리페이'의 백엔드 엔지니어 태호는 대규모 결제 트래픽을 안전하게 처리하기 위해, 주문 상태를 '결제 진행 중'으로 변경하는 트랜잭션에서 동시성 경합을 방지하고자 비관적 락(Pessimistic Lock)을 적용했습니다:

```sql
-- [트랜잭션 A: 주문 상태 갱신]
BEGIN;
SELECT * FROM orders WHERE id = 1001 FOR UPDATE; -- 부모 행 배타적 락
UPDATE orders SET status = 'PAYING' WHERE id = 1001;
-- (외부 PG사 결제 승인 통신 대기 중...)
```

동시에 결제 웹훅 서버에서는 해당 주문에 대한 결제 영수증 행을 자식 테이블인 `payments`에 추가하는 트랜잭션 B가 실행되었습니다:

```sql
-- [트랜잭션 B: 결제 영수증 기록]
BEGIN;
INSERT INTO payments (id, order_id, amount) VALUES (501, 1001, 50000);
```

태호는 두 트랜잭션이 건드리는 테이블이 서로 완전히 다르므로 충돌할 일이 없다고 생각했습니다:
* 트랜잭션 A는 부모 테이블인 `orders`를 잠그고 수정함.
* 트랜잭션 B는 자식 테이블인 `payments`에 새 행을 추가함.

그런데 결제 트래픽이 몰리자마자 데이터베이스 로그에 **치명적인 데드락 에러**가 폭풍처럼 쏟아지며 수백 건의 결제가 롤백되었습니다:

```
ERROR: deadlock detected
DETAIL: Process 18241 waits for ExclusiveLock on tuple (0, 12) of relation "orders"; 
        blocked by process 18242.
Process 18242 waits for ShareLock on transaction 928124; 
        blocked by process 18241.
HINT: See server log for query details.
```

태호는 머리를 감싸 쥐었습니다:  
"트랜잭션 B는 자식 테이블 `payments`에 INSERT를 쳤을 뿐인데, 도대체 왜 부모 테이블 `orders`의 락을 기다리다가 트랜잭션 A와 데드락이 터진 거지?!"

긴급 소집된 데이터베이스 아키텍트 민우 님이 화이트보드에 락 매트릭스를 그리며 설명했습니다:

> "태호 님! 자식 테이블에 행을 INSERT할 때, PostgreSQL은 외래키(FK) 무결성을 보장하기 위해 부모 행(`orders id=1001`)에 대해 내부적으로 묵시적인 **`FOR KEY SHARE`** 락을 자동으로 획득합니다!  
> 그런데 트랜잭션 A가 걸어둔 **`FOR UPDATE`는 PK 컬럼까지 바꿀 수 있는 가장 강력한 락이어서 자식의 `FOR KEY SHARE`와 배타적(Conflict)으로 충돌**합니다!  
> 즉, 부모의 `status`를 바꾸는 동안 자식 테이블의 모든 INSERT가 올스톱되는 거죠!  
> 여기에 트랜잭션 A가 자식 테이블의 다른 행을 건드리려 하거나 상호 교차 대기에 빠지는 순간 **즉시 데드락 사이클이 완성되어 폭사**합니다!  
> 부모의 Primary Key를 변경할 게 아니라면, `FOR UPDATE` 대신 PostgreSQL 9.3부터 지원되는 **`FOR NO KEY UPDATE`**를 써야 합니다!  
> `FOR NO KEY UPDATE`는 자식 외래키 검사의 `FOR KEY SHARE`와 **100% 상호 호환(Non-conflicting)**되므로 대기 0초로 동시에 처리됩니다!"

태호가 쿼리를 `FOR NO KEY UPDATE`로 수정하자, 거짓말처럼 데드락이 0건으로 사라지고 수천 건의 결제 INSERT가 병렬로 초고속 처리되었습니다.

---

## 2. 핵심 이론: PostgreSQL 외래키 검사와 4계층 행 락 매트릭스

### (1) 외래키 무결성 검사 메커니즘
* 자식 테이블에 외래키(`REFERENCES orders(id)`)를 가진 행을 삽입할 때, 부모 행이 트랜잭션 도중 `DELETE`되거나 `id`가 바뀌면 참조 무결성이 파괴됩니다.
* 따라서 PostgreSQL 엔진은 자식 행 INSERT 시 참조 대상인 부모 행에 내부적으로 **`FOR KEY SHARE`** 락을 자동으로 겁니다.

### (2) `FOR UPDATE`의 치명적 맹점
* `FOR UPDATE`는 해당 행의 삭제 또는 Primary Key(외래키 참조 컬럼) 변경을 허용하는 최고 강도의 배타락입니다.
* `FOR UPDATE`는 `FOR KEY SHARE`와 **상호 배타적(Conflict)**이므로, 부모를 잠근 동안 자식 테이블 INSERT가 전면 블로킹됩니다.

### (3) PostgreSQL 9.3+ 4계층 행 락 호환성 매트릭스

| 기존에 걸린 락 \ 요청된 락 | `FOR KEY SHARE` (자식 INSERT) | `FOR SHARE` | `FOR NO KEY UPDATE` (일반 UPDATE) | `FOR UPDATE` (PK 변경/삭제) |
|:---|:---:|:---:|:---:|:---:|
| **`FOR KEY SHARE`** (자식 INSERT) | 🟢 **호환** | 🟢 **호환** | 🟢 **호환 (Conflict 없음!)** | ❌ **충돌 (대기)** |
| **`FOR SHARE`** | 🟢 **호환** | 🟢 **호환** | ❌ **충돌** | ❌ **충돌** |
| **`FOR NO KEY UPDATE`** | 🟢 **호환 (자식 INSERT 통과!)** | ❌ **충돌** | ❌ **충돌** | ❌ **충돌** |
| **`FOR UPDATE`** | ❌ **충돌 (자식 INSERT 블로킹!)** | ❌ **충돌** | ❌ **충돌** | ❌ **충돌** |

* **`FOR NO KEY UPDATE`의 마법**:
  * 부모 행의 비(非)키 일반 컬럼(`status`, `amount` 등)만 변경할 때 사용합니다.
  * 자식 외래키 검사의 `FOR KEY SHARE`와 **완벽히 호환**되므로 락 경합과 데드락이 100% 소멸합니다!

---

## 3. 입출력 규격 및 요구사항

트랜잭션들의 연속된 연산(`LOCK_PARENT`, `INSERT_CHILD`, `LOCK_CHILD`, `COMMIT`, `ROLLBACK`)이 주어졌을 때, PostgreSQL 행 락 호환성 매트릭스와 Wait-For Graph를 기반으로 동시성 및 데드락을 시뮬레이션하고 최종 상태를 판정하는 엔진을 작성하세요.

### 입력 형식 (JSON)
```json
{
  "operations": [
    {"tx_id": "TX_A", "action": "LOCK_PARENT", "parent_id": 1001, "lock_mode": "FOR_UPDATE"},
    {"tx_id": "TX_B", "action": "INSERT_CHILD", "child_id": 501, "parent_id": 1001},
    {"tx_id": "TX_A", "action": "LOCK_CHILD", "child_id": 501, "lock_mode": "FOR_UPDATE"},
    {"tx_id": "TX_B", "action": "COMMIT"},
    {"tx_id": "TX_A", "action": "COMMIT"}
  ]
}
```

* `action` 종류:
  * `LOCK_PARENT`: 부모 행에 락 획득 (`lock_mode`: `"FOR_UPDATE"` 또는 `"FOR_NO_KEY_UPDATE"`)
  * `INSERT_CHILD`: 자식 행에 `FOR_UPDATE` 락을 걸고, 부모 행에 외래키 검증을 위해 묵시적 `FOR_KEY_SHARE` 락을 요청
  * `LOCK_CHILD`: 자식 행에 락 획득 (`lock_mode`: `"FOR_UPDATE"`, `"FOR_SHARE"`)
  * `COMMIT` / `ROLLBACK`: 트랜잭션 종료 및 보유 락 전량 해제, 대기 트랜잭션 깨우기

### 출력 형식 (JSON)
```json
{
  "summary": {
    "lock_requests_total": 4,
    "lock_granted_count": 2,
    "lock_wait_count": 2,
    "deadlock_detected": true,
    "deadlock_cycle": ["TX_A", "TX_B", "TX_A"],
    "committed_transactions": ["TX_B"],
    "aborted_transactions": ["TX_A"],
    "overall_verdict": "FOR_UPDATE_FK_DEADLOCK_DISASTER"
  }
}
```

### 판정 규칙 (`overall_verdict`)
* `deadlock_detected == true`:
  * `"FOR_UPDATE_FK_DEADLOCK_DISASTER"`
* `lock_wait_count == 0` 이고 `len(committed_transactions) > 1`:
  * `"FOR_NO_KEY_UPDATE_OPTIMAL"`
* 그 외:
  * `"BALANCED_EXECUTION"`

---

## 4. 입출력 예시

### 예시 1: FOR UPDATE로 인한 외래키 데드락 참사

#### 입력
```json
{
  "operations": [
    {"tx_id": "TX_A", "action": "LOCK_PARENT", "parent_id": 1001, "lock_mode": "FOR_UPDATE"},
    {"tx_id": "TX_B", "action": "INSERT_CHILD", "child_id": 501, "parent_id": 1001},
    {"tx_id": "TX_A", "action": "LOCK_CHILD", "child_id": 501, "lock_mode": "FOR_UPDATE"},
    {"tx_id": "TX_B", "action": "COMMIT"},
    {"tx_id": "TX_A", "action": "COMMIT"}
  ]
}
```

#### 출력
```json
{
  "summary": {
    "lock_requests_total": 4,
    "lock_granted_count": 2,
    "lock_wait_count": 2,
    "deadlock_detected": true,
    "deadlock_cycle": ["TX_A", "TX_B", "TX_A"],
    "committed_transactions": ["TX_B"],
    "aborted_transactions": ["TX_A"],
    "overall_verdict": "FOR_UPDATE_FK_DEADLOCK_DISASTER"
  }
}
```

### 예시 2: FOR NO KEY UPDATE 적용으로 충돌 없는 완벽한 동시 처리

#### 입력
```json
{
  "operations": [
    {"tx_id": "TX_A", "action": "LOCK_PARENT", "parent_id": 1001, "lock_mode": "FOR_NO_KEY_UPDATE"},
    {"tx_id": "TX_B", "action": "INSERT_CHILD", "child_id": 501, "parent_id": 1001},
    {"tx_id": "TX_B", "action": "COMMIT"},
    {"tx_id": "TX_A", "action": "LOCK_CHILD", "child_id": 501, "lock_mode": "FOR_UPDATE"},
    {"tx_id": "TX_A", "action": "COMMIT"}
  ]
}
```

#### 출력
```json
{
  "summary": {
    "lock_requests_total": 4,
    "lock_granted_count": 4,
    "lock_wait_count": 0,
    "deadlock_detected": false,
    "deadlock_cycle": [],
    "committed_transactions": ["TX_A", "TX_B"],
    "aborted_transactions": [],
    "overall_verdict": "FOR_NO_KEY_UPDATE_OPTIMAL"
  }
}
```
