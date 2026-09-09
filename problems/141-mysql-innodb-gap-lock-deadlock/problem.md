# [왜 없는 데이터를 조회/수정했을 뿐인데 트랜잭션이 데드락으로 폭사해요?!: MySQL InnoDB 갭 락(Gap Lock) / 넥스트 키 락(Next-Key Lock) 경합과 데드락(Deadlock)]

## 1. 장애 시나리오: "존재하지도 않는 쿠폰을 발급하려다 전사 결제/주문 DB가 마비된 사태"

대규모 선착순 한정판 쿠폰 이벤트 오픈 당일, 결제/프로모션 서버의 에러 로그에 초당 수백 건의 트랜잭션 롤백 에러가 폭발하기 시작했습니다:
```text
org.springframework.dao.CannotAcquireLockException: 
Deadlock found when trying to get lock; try restarting transaction; 
nested exception is java.sql.SQLException: Deadlock found when trying to get lock...
```

백엔드 개발팀은 소스코드를 확인하고 경악을 금치 못했습니다:
```java
@Transactional
public void issueCoupon(String couponCode, Long userId) {
    // 1. 이미 발급된 쿠폰인지 비관적 락으로 조회
    Coupon coupon = couponRepository.findByCodeForUpdate(couponCode);
    
    // 2. 존재하지 않는 신규 쿠폰이면 새로 생성하여 발급
    if (coupon == null) {
        couponRepository.save(new Coupon(couponCode, userId));
    }
}
```

개발자들의 의문:
> "아니, 데이터베이스에 아직 존재하지도 않는(`null`) 행인데, 대체 무엇과 무엇이 락을 걸고 싸워서 데드락이 난다는 말인가요? 존재하지도 않는 유령 데이터끼리 멱살을 잡고 싸우나요?!"

범인은 바로 **MySQL InnoDB 스토리지 엔진의 기본 격리 수준인 `REPEATABLE READ`와 갭 락(Gap Lock)**이었습니다.
1. `T1`과 `T2`가 거의 동시에 같은 범위의 존재하지 않는 `couponCode`를 `SELECT ... FOR UPDATE`로 조회합니다.
2. InnoDB는 팬텀 리드(Phantom Read)를 방지하기 위해 해당 인덱스 구간에 **갭 락(Gap Lock)**을 겁니다.
3. **치명적인 점**: 갭 락은 "다른 녀석이 끼어들지 못하게 막는 순수한 억제 락"이므로, **갭 락끼리는 서로 충돌하지 않고 둘 다 획득에 성공**합니다!
4. 그 직후, `T1`이 `INSERT`를 시도합니다. 삽입을 위해 `Insert Intention Lock`을 요구하지만, **`T2`가 쥐고 있는 갭 락 때문에 대기(Wait)** 상태에 빠집니다.
5. 거의 동시에 `T2`도 `INSERT`를 시도합니다. 하지만 **`T1`이 쥐고 있는 갭 락 때문에 대기** 상태에 빠집니다!
6. **상호 대기 사이클(Deadlock)** 형성! InnoDB 데드락 감지기(Deadlock Detector)가 출동하여 `T2`를 강제 롤백(희생자)시키고 폭사하게 만든 것입니다.

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 MySQL InnoDB의 기본 격리 수준(`REPEATABLE READ`) 하에서 발생하는 **레코드 락(Record Lock), 갭 락(Gap Lock), 인서트 인텐션 락(Insert Intention Lock)**의 경합과 데드락 사이클 감지 메커니즘을 시뮬레이션합니다.

### (1) 테이블 인덱스 상태와 갭(Gap)의 정의
- 테이블의 기본키(정수형) 오름차순으로 정렬된 키 목록 $[K_0, K_1, \dots, K_{m-1}]$이 주어집니다.
- 갭은 인덱스 레코드 사이의 빈 구간을 의미하며, 다음과 같이 정의됩니다:
  - 첫 레코드 이전 구간: $(-\infty, K_0)$
  - 레코드 사이 구간: $(K_i, K_{i+1})$
  - 마지막 레코드 이후 구간 (Supremum): $(K_{m-1}, +\infty)$
  - 만약 테이블이 완전히 비어있다면: $(-\infty, +\infty)$

### (2) 락의 획득 및 호환성 규칙
1. **`SELECT_FOR_UPDATE <tx> <key>` (또는 `UPDATE <tx> <key>`)**:
   - `key`가 이미 테이블에 존재하는 레코드(커밋됨 또는 다른 트랜잭션이 삽입 중)인 경우:
     - 해당 키에 대해 **배타적 레코드 락(Record Lock X)**을 획득하려 합니다.
     - 다른 트랜잭션이 이미 해당 레코드 락을 쥐고 있다면 대기(Wait)합니다.
   - `key`가 테이블에 존재하지 않는 경우:
     - `key`가 속한 빈 구간 $(low, high)$에 대해 **갭 락(Gap Lock)**을 획득합니다.
     - **갭 락은 다른 트랜잭션의 갭 락과 상호 호환**됩니다 (여러 트랜잭션이 동일한 갭에 갭 락을 동시에 쥘 수 있음).
2. **`INSERT <tx> <key>`**:
   - `key`가 속한 구간 $(low, high)$에 대해 **인서트 인텐션 락(Insert Intention Lock)**을 요청합니다.
   - **경합 조건**: 해당 구간 $(low, high)$에 대해 **다른 활성 트랜잭션이 갭 락을 쥐고 있다면**, `INSERT`는 진행되지 못하고 해당 트랜잭션들이 락을 해제할 때까지 **대기(Wait)** 상태에 돌입합니다.
   - 다른 트랜잭션의 갭 락이 없다면 삽입이 성공하고, 해당 `key`에 대한 레코드 락을 `tx`가 획득합니다 (임시 커밋 대기 상태).

### (3) 데드락 감지 (Wait-For Graph Cycle Detection)
- 어떤 트랜잭션 $A$가 $B$가 쥐고 있는 락 때문에 대기해야 할 때, 대기 그래프(Wait-For Graph)에 $A 	o B$ 간선이 추가됩니다.
- 간선을 추가했을 때 **사이클(순환 대기, 예: $A 	o B 	o A$)이 발생하면 즉시 데드락(Deadlock)이 판정**됩니다!
- **데드락 희생자(Victim)**: 사이클을 유발한 현재 트랜잭션 $A$가 즉시 희생자로 지정되어 **강제 롤백(ABORT/ROLLBACK)** 처리됩니다 (`DEADLOCKS += 1`, `ROLLED_BACK += 1`).
- 희생된 트랜잭션은 자신이 쥐고 있던 모든 락(갭 락, 레코드 락)을 즉시 해제하며, 대기 중이던 다른 트랜잭션들이 깨어납니다. 해당 트랜잭션의 이후 명령은 모두 무시됩니다.

### (4) 트랜잭션 종료 및 대기자 기상 규칙
- **`COMMIT <tx>`**:
  - `tx`가 삽입했던 키들이 테이블에 영구 커밋(정렬된 인덱스에 추가)됩니다.
  - `tx`가 쥐고 있던 모든 락이 해제됩니다.
  - `COMMITTED += 1`
  - `tx` 때문에 대기 중이던 트랜잭션들이 락을 재검사하여 FIFO 순서대로 깨어납니다.
- **`ROLLBACK <tx>`**:
  - `tx`의 미커밋 삽입이 취소되고, 모든 락이 해제됩니다.
  - `ROLLED_BACK += 1`
  - 대기 중이던 트랜잭션들이 깨어납니다.

---

## 3. 입력 형식

- 첫째 줄에 초기 테이블 레코드 수 $K$ ($0 \le K \le 100$)가 주어집니다.
- 둘째 줄에 초기 레코드 키 $K$개가 공백으로 구분되어 오름차순으로 주어집니다 ($K=0$이면 빈 줄).
- 셋째 줄에 작업의 수 $M$ ($1 \le M \le 500$)이 주어집니다.
- 넷째 줄부터 $M$개 줄에 걸쳐 각 작업 명령이 순서대로 주어집니다:
  - `BEGIN <tx>`
  - `SELECT_FOR_UPDATE <tx> <key>`
  - `UPDATE <tx> <key>`
  - `INSERT <tx> <key>`
  - `COMMIT <tx>`
  - `ROLLBACK <tx>`

## 4. 출력 형식

- 모든 작업이 종료된 후, 다음 정보를 한 줄에 출력합니다:
  - `COMMITTED: <성공트랜잭션수> ROLLED_BACK: <롤백트랜잭션수> DEADLOCKS: <데드락발생횟수> ROWS: <최종정렬된키목록콤마구분>`
  - 최종 키가 하나도 없으면 `ROWS: EMPTY`를 출력합니다.

---

## 5. 입출력 예제

### 예제 1
#### 입력
```text
2
10 30
7
BEGIN T1
BEGIN T2
SELECT_FOR_UPDATE T1 15
SELECT_FOR_UPDATE T2 20
INSERT T1 15
INSERT T2 20
COMMIT T1
```
#### 출력
```text
COMMITTED: 1 ROLLED_BACK: 1 DEADLOCKS: 1 ROWS: 10,15,30
```
**설명**:
- T1과 T2가 각각 존재하지 않는 15, 20을 조회하여 갭 `(10, 30)`에 갭 락을 동시에 겁니다.
- T1이 15를 INSERT하려다 T2의 갭 락에 막혀 대기합니다 (T1 -> T2).
- T2가 20을 INSERT하려다 T1의 갭 락에 막혀 대기하려 합니다. 순환(T2 -> T1 -> T2)이 발생하므로 T2가 데드락 희생자로 롤백됩니다!
- T2가 죽으면서 락이 풀려 T1의 15 INSERT가 성공하고, T1이 COMMIT하여 최종 레코드는 `10, 15, 30`이 됩니다.

### 예제 2
#### 입력
```text
2
10 30
6
BEGIN T1
BEGIN T2
INSERT T1 15
INSERT T2 25
COMMIT T1
COMMIT T2
```
#### 출력
```text
COMMITTED: 2 ROLLED_BACK: 0 DEADLOCKS: 0 ROWS: 10,15,25,30
```
**설명**:
- 선행 갭 락이 없으므로, 두 트랜잭션의 `INSERT`는 충돌 없이 즉시 수행됩니다.
