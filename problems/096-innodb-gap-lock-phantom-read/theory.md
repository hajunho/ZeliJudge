# CS 이론 백서: MySQL InnoDB 갭 락(Gap Lock), 넥스트 키 락(Next-Key Lock)과 유령 읽기(Phantom Read) 방어의 덫

> **"두 트랜잭션이 테이블에 존재하지도 않는 서로 다른 ID(5번과 7번)를 INSERT했을 뿐인데, 왜 서로 락을 쥐고 데드락(Deadlock)으로 폭사하나요?!"**  
> 이 문제는 데이터베이스 엔진의 버그가 아니라, **MySQL InnoDB가 Repeatable Read 격리수준에서 '유령 읽기(Phantom Read)'를 원천 차단하기 위해 레코드 사이의 빈 공간(Gap)에 락을 거는 메커니즘** 때문에 발생합니다.

---

## 1. 현실 비유: 주차장 빈 칸에 돗자리 깔기(Gap Lock)와 두 운전자의 비극

주차장에 차들이 번호 순서대로 주차되어 있습니다. 현재 **10번 칸**과 **20번 칸**에만 차가 주차되어 있고, 그 사이의 **11번 ~ 19번 칸은 텅 빈 공간(Gap)**입니다.

```
[10번 차] ---------- ( 11번 ~ 19번 빈 공간 : Gap ) ---------- [20번 차]
```

### 1단계: 빈 공간에 돗자리 깔기 (Gap Lock 획득)
운전자 A와 운전자 B가 주차장에 들어옵니다:
- **운전자 A**: "나 이 근처에 차를 댈지도 몰라!"라며 11번~19번 빈 공간 전체에 커다란 돗자리를 깝니다(**Gap Lock**).
- **운전자 B**: "나도 이 근처에 댈 거야!"라며 운전자 A의 돗자리 위에 자기 돗자리를 겹쳐서 깝니다.  
  *(놀랍게도 InnoDB에서 **Gap Lock끼리는 서로 간섭하지 않고 평화롭게 공존**할 수 있습니다!)*

### 2단계: 실제로 주차하려는 순간 (Insert Intention Lock과의 충돌)
이제 두 운전자가 실제로 차를 주차(INSERT)하려고 합니다:
- **운전자 A**가 15번 칸에 차를 넣으려 합니다(`INSERT INTO t VALUES (15)`).  
  $\rightarrow$ 하지만 운전자 B의 돗자리가 깔려 있습니다! B가 "내 돗자리 밟지 마라!"며 A의 진입을 막아섭니다. A는 대기(`LOCK_WAIT`) 상태에 빠집니다.
- **운전자 B**가 18번 칸에 차를 넣으려 합니다(`INSERT INTO t VALUES (18)`).  
  $\rightarrow$ 하지만 이번엔 운전자 A의 돗자리가 깔려 있습니다! A도 "너야말로 내 돗자리 밟지 마라!"며 B의 진입을 막아섭니다.
- **결과**:  
  운전자 A는 B가 돗자리를 걷기를 기다리고, 운전자 B는 A가 돗자리를 걷기를 기다립니다.  
  $\rightarrow$ **영원히 서로를 기다리는 상호 대기 사이클: 데드락(Deadlock) 폭발!**

---

## 2. 유령 읽기(Phantom Read)란 무엇인가?

트랜잭션 격리수준(Isolation Level)의 핵심 과제 중 하나는 **유령 읽기(Phantom Read)** 방지입니다:

```sql
-- 트랜잭션 1
START TRANSACTION;
SELECT * FROM users WHERE age BETWEEN 10 AND 20 FOR UPDATE; -- (결과: 1건)

-- 그 사이 트랜잭션 2가 새로운 행 삽입
INSERT INTO users (id, age) VALUES (99, 15);
COMMIT;

-- 트랜잭션 1이 동일한 쿼리를 다시 실행
SELECT * FROM users WHERE age BETWEEN 10 AND 20 FOR UPDATE; -- (결과: 2건?! 유령 행 출현!)
```

트랜잭션 1이 범위 조회를 했을 때, 분명 처음엔 없던 새로운 행이 트랜잭션 도중에 갑자기 유령처럼 나타나는 현상을 Phantom Read라고 합니다.

---

## 3. MySQL InnoDB의 4대 잠금(Lock) 유형

MySQL InnoDB는 Repeatable Read 격리수준에서 유령 행의 침투를 막기 위해 독특한 잠금 구조를 사용합니다:

| 잠금 유형 | 대상 | 설명 |
| :--- | :--- | :--- |
| **Record Lock (레코드 락)** | 실제 존재하는 인덱스 레코드 | 특정 행(`id = 10`) 자체에 거는 락. 타 트랜잭션의 수정/삭제 차단. |
| **Gap Lock (갭 락)** | 인덱스 레코드 사이의 빈 공간 | 레코드 사이(`10 < id < 20`)에 새 행이 INSERT되는 것을 차단하는 락. |
| **Next-Key Lock (넥스트 키 락)** | `Gap Lock + Record Lock` | 빈 공간과 그 구간의 오른쪽 끝 레코드를 함께 묶어서 잠그는 락 (`10 < id <= 20`). |
| **Insert Intention Lock (삽입 의도 락)** | 삽입할 대상 Gap | 새 행을 INSERT하기 직전에 거는 특수 락. Gap Lock과 정면 충돌하여 대기 발생. |

---

## 4. 왜 서로 다른 키를 INSERT하는데 데드락이 발생하는가?

이 현상이 개발자들을 가장 멘붕에 빠뜨리는 이유는 **"충돌 호환성 테이블(Lock Compatibility Matrix)"의 특이성** 때문입니다:

```
                  [이미 걸려 있는 락]
요청하는 락     | Record Lock | Gap Lock | Insert Intention Lock
----------------+-------------+----------+----------------------
Record Lock     |    충돌     |   호환   |        호환
Gap Lock        |    호환     |   호환   |        호환
Insert Intention|    호환     |   충돌   |        호환
```

1. **Gap Lock끼리는 호환된다**:
   - 트랜잭션 1이 `WHERE id = 15 FOR UPDATE` (15는 없음)로 `(10, 20)` Gap Lock을 획득합니다.
   - 트랜잭션 2도 `WHERE id = 18 FOR UPDATE` (18은 없음)로 `(10, 20)` Gap Lock을 획득합니다.
   - 둘 다 Gap Lock이므로 충돌 없이 둘 다 성공합니다!
2. **Insert Intention Lock은 Gap Lock과 충돌한다**:
   - 트랜잭션 1이 `INSERT (15)`를 시도합니다. 이는 `(10, 20)` 구간에 대한 Insert Intention Lock입니다.
   - 하지만 트랜잭션 2가 이미 `(10, 20)` Gap Lock을 쥐고 있으므로 트랜잭션 1은 멈춥니다(`Lock Wait`).
   - 트랜잭션 2도 `INSERT (18)`을 시도합니다.
   - 하지만 트랜잭션 1이 `(10, 20)` Gap Lock을 쥐고 있으므로 트랜잭션 2도 멈춥니다.
3. **데드락 판정**:
   - MySQL의 데드락 감지기(Deadlock Detector)가 Wait-For Graph에서 사이클($T_1 \to T_2 \to T_1$)을 발견하고, 트랜잭션 하나를 즉시 강제 롤백(`Deadlock found when trying to get lock`)시킵니다!

---

## 5. 실무 아키텍트의 해결책 (체크리스트)

1. **격리수준을 `READ COMMITTED (RC)`로 변경 (글로벌 표준 패턴)**:
   - 오라클, PostgreSQL, SQL Server는 기본 격리수준이 `READ COMMITTED`입니다.
   - MySQL InnoDB에서도 격리수준을 `READ COMMITTED`로 낮추면 **Gap Lock이 완전히 비활성화**되어 데드락이 90% 이상 사라집니다.
   - *(주의: RC 격리수준 사용 시 MySQL의 `binlog_format`을 반드시 `ROW`로 설정해야 복제 정합성이 보장됩니다!)*
2. **고유 인덱스(Unique Index) 등치 조건(`=`) 사용**:
   - 고유 인덱스로 존재하는 단일 행을 정확히 등치(`WHERE id = 10`)로 조회할 때는 Gap Lock이 걸리지 않고 순수한 **Record Lock**으로 축소됩니다.
3. **순차적 키(Auto-Increment, TSID) 삽입**:
   - 무작위 ID 대신 순차적으로 증가하는 ID를 삽입하면 항상 맨 오른쪽 끝 Gap(`supremum`)에만 접근하므로 중간 Gap에서의 경합 데드락이 발생하지 않습니다.
