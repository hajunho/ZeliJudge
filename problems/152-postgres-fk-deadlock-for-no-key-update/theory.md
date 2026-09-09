# PostgreSQL 외래키(FK) 검사와 FOR UPDATE vs FOR NO KEY UPDATE 락 매트릭스 & 데드락

## 1. 개요 및 실무 장애 시나리오: "부모 테이블을 잠갔는데 왜 자식 테이블 INSERT와 데드락이 터져요?!"

핀테크 결제 플랫폼 '젤리페이'의 백엔드 엔지니어 태호는 대규모 결제 트래픽을 안전하게 처리하기 위해, 주문 상태를 '결제 진행 중'으로 변경하는 트랜잭션에서 동시성 경합을 방지하고자 비관적 락(Pessimistic Lock)을 적용했습니다:

```sql
-- [트랜잭션 A: 주문 상태 갱신]
BEGIN;
SELECT * FROM orders WHERE id = 1001 FOR UPDATE; -- 부모 행 배타적 락
UPDATE orders SET status = 'PAYING' WHERE id = 1001;
-- (외부 PG 결제 처리 대기 중...)
```

동시에 결제 웹훅 서버에서는 해당 주문에 대한 결제 영수증 행을 자식 테이블인 `payments`에 추가하는 트랜잭션 B가 실행되었습니다:

```sql
-- [트랜잭션 B: 결제 영수증 기록]
BEGIN;
INSERT INTO payments (id, order_id, amount) VALUES (501, 1001, 50000);
```

태호는 두 트랜잭션이 건드리는 테이블이 서로 다르다고 생각했습니다:
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

---

## 2. 참사의 주범: PostgreSQL의 외래키(FK) 무결성 검사 메커니즘

### (1) 외래키 INSERT 시 백엔드에서 일어나는 일
`payments` 테이블에는 다음과 같은 외래키 제약조건이 걸려 있습니다:
```sql
ALTER TABLE payments 
ADD CONSTRAINT fk_orders 
FOREIGN KEY (order_id) REFERENCES orders(id);
```

자식 테이블에 `order_id = 1001`인 행을 `INSERT`할 때, 데이터베이스는 무결성을 보장하기 위해 반드시 확인해야 합니다:
> *"부모 테이블 `orders`에 `id = 1001`인 행이 실제로 존재하는가? 그리고 내가 INSERT를 마칠 때까지 다른 트랜잭션이 부모 행을 DELETE하거나 PK를 다른 값으로 바꾸지 못하게 막아야 한다!"*

이 무결성을 보장하기 위해, PostgreSQL 엔진은 자식 행을 INSERT할 때 **부모 행(`orders id=1001`)에 대해 내부적으로 묵시적인 `FOR KEY SHARE` 락을 자동으로 획득**합니다!

---

### (2) `FOR UPDATE`의 치명적 맹점: `FOR KEY SHARE`와의 상호 충돌
문제는 트랜잭션 A가 부모 행에 걸어둔 **`SELECT ... FOR UPDATE`**입니다.

* `FOR UPDATE`는 해당 행의 **Primary Key(외래키 참조 컬럼)까지 변경하거나 행을 삭제할 수도 있는 가장 강력한 배타락**입니다.
* 따라서 `FOR UPDATE`는 자식의 외래키 검증 락인 **`FOR KEY SHARE`와 완벽히 상호 배타적(Conflict)**입니다!

```
[트랜잭션 A]                                    [트랜잭션 B]
     │                                               │
     │── (1) orders id=1001 잠금 (FOR UPDATE)        │
     │   (배타적 락 획득 성공!)                      │
     │                                               │
     │                                               │── (2) payments에 INSERT (order_id=1001)
     │                                               │   (PostgreSQL이 부모 행에 FOR KEY SHARE 요구!)
     │                                               │   [FOR UPDATE와 충돌하여 블로킹 대기 발생!] ⏳
     │                                               │
     │── (3) payments 테이블 통계/이력 조회/락 시도 ─│
     │   [트랜잭션 B가 잡은 락과 상호 교착!]         │
     │                                               │
     ▼                                               ▼
               💥 DEADLOCK DETECTED! 트랜잭션 폭사! 💥
```

트랜잭션 A는 단순히 주문의 `status` 컬럼만 변경했을 뿐인데, `FOR UPDATE`를 썼다는 이유만으로 **자식 테이블의 모든 INSERT를 올스톱시키고 데드락을 유발**한 것입니다!

---

## 3. 구원 투수: PostgreSQL 9.3+ 4계층 행 락과 `FOR NO KEY UPDATE`

PostgreSQL 9.3부터 개발진은 이 고질적인 외래키 블로킹 문제를 해결하기 위해 행 수준 락을 4단계로 세분화했습니다:

1. **`FOR UPDATE` (가장 강함)**:
   * 행의 삭제(`DELETE`) 또는 Primary Key / Unique Key 컬럼을 변경할 때 사용.
   * 모든 락(`FOR KEY SHARE` 포함)과 충돌.
2. **`FOR NO KEY UPDATE` (실무 표준 구원 투수!)**:
   * PK나 Unique Key가 아닌 **일반 컬럼(상태, 금액, 업데이트 시각 등)만 수정**할 때 사용.
   * **`FOR KEY SHARE`와 100% 상호 호환 (Non-Conflicting)!**
3. **`FOR SHARE`**:
   * 다른 트랜잭션이 데이터를 읽을 수는 있지만 수정하지 못하게 할 때 사용.
4. **`FOR KEY SHARE` (외래키 전용)**:
   * 자식 테이블이 부모의 PK 존재를 보장받기 위해 사용하는 최소한의 읽기 락.
   * `FOR NO KEY UPDATE`와 완벽히 공존 가능!

---

## 4. PostgreSQL 행 수준 락 호환성 매트릭스 (Lock Compatibility Matrix)

| 기존에 걸린 락 \ 요청된 락 | `FOR KEY SHARE` (자식 INSERT) | `FOR SHARE` | `FOR NO KEY UPDATE` (일반 UPDATE) | `FOR UPDATE` (PK 변경/삭제) |
|:---|:---:|:---:|:---:|:---:|
| **`FOR KEY SHARE`** (자식 INSERT) | 🟢 **호환** | 🟢 **호환** | 🟢 **호환 (Conflict 없음!)** | ❌ **충돌 (대기)** |
| **`FOR SHARE`** | 🟢 **호환** | 🟢 **호환** | ❌ **충돌** | ❌ **충돌** |
| **`FOR NO KEY UPDATE`** | 🟢 **호환 (자식 INSERT 통과!)** | ❌ **충돌** | ❌ **충돌** | ❌ **충돌** |
| **`FOR UPDATE`** | ❌ **충돌 (자식 INSERT 블로킹!)** | ❌ **충돌** | ❌ **충돌** | ❌ **충돌** |

### 실무 적용: 1단어 변경의 기적
```sql
-- [수정 전 (데드락 유발)]
SELECT * FROM orders WHERE id = 1001 FOR UPDATE;

-- [수정 후 (100% 데드락 소멸!)]
SELECT * FROM orders WHERE id = 1001 FOR NO KEY UPDATE;
```

JPA를 사용하는 경우:
```java
// 수정 전: LockModeType.PESSIMISTIC_WRITE (PostgreSQL에서 FOR UPDATE 생성)
// 수정 후: 
@QueryHints({@QueryHint(name = "jakarta.persistence.lock.timeout", value = "3000")})
// 또는 하이버네이트 전용 LockMode.UPGRADE_NOWAIT / PESSIMISTIC_WRITE with custom dialect
```

`FOR NO KEY UPDATE`를 적용하면 부모 행의 주문 상태를 바꾸는 동안에도 자식 테이블에 수천 건의 결제 영수증이 **락 대기 0초로 동시에 INSERT**되며 데드락이 100% 원천 박멸됩니다.
