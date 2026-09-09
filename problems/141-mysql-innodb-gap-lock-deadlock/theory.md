# [MySQL InnoDB 갭 락(Gap Lock), 넥스트 키 락(Next-Key Lock)과 데드락(Deadlock) 아키텍처]

## 1. 개요: 팬텀 리드(Phantom Read)를 막기 위한 InnoDB의 고육지책

관계형 데이터베이스의 표준 격리 수준(SQL-92)에서 `REPEATABLE READ`는 동일한 트랜잭션 내에서 동일한 쿼리를 여러 번 실행했을 때 기존에 읽었던 행의 데이터가 변경되지 않음을 보장하지만, **새로운 행이 끼어드는 현상(Phantom Read, 유령 읽기)**은 허용하는 것이 표준 스펙입니다.

하지만 **MySQL의 InnoDB 스토리지 엔진은 기본 격리 수준인 `REPEATABLE READ`에서 팬텀 리드를 완벽히 방지**하도록 설계되었습니다.
이를 위해 도입된 독특한 락킹 메커니즘이 바로 **넥스트 키 락(Next-Key Lock)**과 **갭 락(Gap Lock)**입니다.

---

## 2. InnoDB 락의 3대 핵심 유형

### (1) 레코드 락 (Record Lock)
- 인덱스 레코드 자체에 거는 락입니다 (예: `id = 10` 레코드 자체).
- PK나 Unique 인덱스로 존재하는 단일 행을 `FOR UPDATE`할 때 걸립니다.

### (2) 갭 락 (Gap Lock)
- **인덱스 레코드와 레코드 사이의 '빈 공간(Gap)'**에 거는 락입니다.
- 예를 들어 인덱스에 10과 30이 있다면, `(10, 30)` 사이 구간 전체가 갭입니다.
- **존재 목적**: 다른 트랜잭션이 이 빈 공간에 새로운 레코드를 `INSERT`하지 못하도록 차단하는 것입니다.
- **갭 락의 특이점 (Purely Inhibitive)**:
  - 갭 락의 유일한 목적은 "다른 트랜잭션의 INSERT를 막는 것"입니다.
  - 따라서 **갭 락끼리는 전혀 충돌하지 않습니다!**
  - 트랜잭션 A가 `(10, 30)`에 갭 락을 걸고 있어도, 트랜잭션 B 역시 `(10, 30)`에 갭 락을 중복으로 획득할 수 있습니다.

### (3) 인서트 인텐션 락 (Insert Intention Lock)
- `INSERT` 구문이 실행될 때, 삽입하려는 위치의 갭에 대해 요청하는 특수한 형태의 갭 락입니다.
- "이 갭에 데이터를 넣으려고 대기 중이다"라는 의도를 표시합니다.
- **인서트 인텐션 락끼리는 충돌하지 않습니다** (동일 갭에 서로 다른 키를 삽입하는 여러 트랜잭션은 병렬 처리 가능).
- **하지만 기존의 갭 락(Gap Lock)과는 배타적(Conflict)입니다!**
  - 누군가 해당 구간에 갭 락을 쥐고 있다면, 인서트 인텐션 락은 대기(Wait)해야 합니다.

| 요청 락 \ 기존 보유 락 | Record Lock (X) | Gap Lock (X/S) | Insert Intention Lock |
| :--- | :---: | :---: | :---: |
| **Record Lock (X)** | ❌ 충돌 (대기) | ⭕ 호환 | ⭕ 호환 |
| **Gap Lock (X/S)** | ⭕ 호환 | ⭕ **호환 (공유 가능!)** | ⭕ 호환 |
| **Insert Intention Lock** | ⭕ 호환 | ❌ **충돌 (대기!)** | ⭕ 호환 |

---

## 3. 실무 데드락 참사의 시나리오 상세 분석

### 왜 "없는 데이터"를 조회했는데 데드락이 발생하는가?

쿠폰 발급, 유저 가입, 선착순 재고 예약 등 실무에서 흔히 쓰이는 **"조회 후 없으면 생성(Check-then-Insert)"** 로직에서 발생합니다.

```text
Time | Transaction 1                        | Transaction 2
-----+--------------------------------------+-------------------------------------
T1   | BEGIN;                               | BEGIN;
T2   | SELECT * FROM coupon                 |
     | WHERE id = 15 FOR UPDATE;            |
     | (15는 없음 -> (10, 30) Gap Lock 획득) |
T3   |                                      | SELECT * FROM coupon
     |                                      | WHERE id = 20 FOR UPDATE;
     |                                      | (20은 없음 -> (10, 30) Gap Lock 획득!)
     |                                      | ※ 갭 락끼리는 호환되므로 T2도 즉시 획득!
T4   | INSERT INTO coupon (id) VALUES (15);  |
     | (T2의 (10, 30) 갭 락 때문에 대기!)   |
T5   |                                      | INSERT INTO coupon (id) VALUES (20);
     |                                      | (T1의 (10, 30) 갭 락 때문에 대기!)
     |                                      | 💥 상호 교착(Deadlock Cycle) 감지!
     |                                      | -> MySQL이 T2를 강제 롤백(Deadlock Victim)시킴!
```

### `SHOW ENGINE INNODB STATUS` 로그 분석
실무에서 데드락 발생 시 로그를 열어보면 다음과 같은 패턴을 볼 수 있습니다:
```text
------------------------
LATEST DETECTED DEADLOCK
------------------------
*** (1) TRANSACTION:
TRANSACTION 12345, ACTIVE 2 sec inserting
mysql tables in use 1, locked 1
LOCK WAIT 2 lock struct(s), heap size 1136, 1 row lock(s)
MySQL thread id 10, OS thread handle 1234, query id 5000 localhost root update
insert into coupon (id) values (15)
*** (1) WAITING FOR THIS LOCK TO BE GRANTED:
RECORD LOCKS space id 2 page no 3 n bits 72 index PRIMARY of table `test`.`coupon` 
trx id 12345 lock_mode X locks gap before rec insert intention waiting

*** (2) TRANSACTION:
TRANSACTION 12346, ACTIVE 2 sec inserting
...
insert into coupon (id) values (20)
*** (2) HOLDS THE LOCK(S):
RECORD LOCKS space id 2 page no 3 n bits 72 index PRIMARY of table `test`.`coupon` 
trx id 12346 lock_mode X locks gap before rec
*** (2) WAITING FOR THIS LOCK TO BE GRANTED:
... lock_mode X locks gap before rec insert intention waiting
*** WE ROLL BACK TRANSACTION (2)
```
- 트랜잭션 1은 `insert intention waiting`
- 트랜잭션 2는 `locks gap before rec`을 쥐고 있으면서 자신도 `insert intention waiting`
- 둘이 서로를 물고 늘어지는 전형적인 갭 락 발 데드락입니다.

---

## 4. 실무 해결책 및 모범 가이드 (Best Practices)

### 해결책 1: 격리 수준을 `READ COMMITTED` (RC)로 변경
- 글로벌 또는 세션 격리 수준을 `READ COMMITTED`로 낮추면, InnoDB는 외래키 검사와 유니크 키 중복 체크를 제외하고 **갭 락을 완전히 비활성화**합니다.
- 토스, 당근, 배달의민족 등 대규모 트래픽을 다루는 많은 국내외 유수 테크 기업들의 기본 DB 설정이 `READ COMMITTED`인 주된 이유 중 하나가 바로 이 갭 락 경합 및 데드락 방지입니다.

### 해결책 2: Redis 분산 락 (Redisson) 또는 Named Lock 활용
- 비관적 DB 락(`SELECT FOR UPDATE`) 대신, 비즈니스 키(`coupon:code:XYZ`) 단위로 Redis 분산 락을 획득하여 동일 리소스에 대한 접근을 애플리케이션 레벨에서 직렬화(Serialize)합니다.

### 해결책 3: 조회 없이 삽입(Optimistic Insert) 후 유니크 제약조건 위반 예외 처리
- `SELECT ... FOR UPDATE`로 미리 존재 여부를 확인하려 하지 말고, Unique Index가 걸린 컬럼에 무조건 `INSERT`를 시도합니다.
- 이미 존재하면 DB가 `DuplicateKeyException`을 던지므로, 이를 애플리케이션 코드에서 캐치하여 처리합니다.

### 해결책 4: `INSERT ... ON DUPLICATE KEY UPDATE` 구문 활용
- MySQL 고유 구문을 통해 원자적(Atomic) 업서트(Upsert)를 수행합니다.
