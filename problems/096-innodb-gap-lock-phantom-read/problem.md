# 096. 데이터가 없어서 잠금 걸었더니 다른 사람이랑 데드락이 터졌어요?!: MySQL InnoDB 갭 락(Gap Lock)과 넥스트 키 락(Next-Key Lock)의 팬텀 리드 방어와 데드락 미스터리

---

## 1. 비극의 시작 (Real-World Disaster)

스타트업 개발자 민수는 회원가입 및 추천인 이벤트 시스템을 개발하고 있었습니다.  
동일한 유저가 동시에 가입 요청을 연타해 중복 데이터가 들어가는 것을 막기 위해, 가입 전 트랜잭션을 열고 추천인 코드 및 유저 고유 식별자(`user_id=15`)의 존재 여부를 배타적 잠금으로 확인했습니다:

```sql
START TRANSACTION;
-- 아직 가입되지 않은 신규 user_id=15 조회
SELECT * FROM users WHERE user_id = 15 FOR UPDATE;

-- 데이터가 없으면 신규 유저 INSERT
INSERT INTO users (user_id, name) VALUES (15, '홍길동');
COMMIT;
```

민수는 당당했습니다:  
*"어차피 DB에 아직 15번 데이터가 없으니까 아무 레코드도 잠기지 않겠지? 단지 안전장치로 잠금을 걸어둔 것뿐이야!"*

하지만 마케팅 푸시 알림이 발송되고 수만 명의 신규 유저가 동시 가입을 시도하자마자, 데이터베이스 슬로우 쿼리 알람과 함께 끔찍한 에러가 전사 슬랙 채널을 도배했습니다:

```text
ERROR 1213 (40001): Deadlock found when trying to get lock; try restarting transaction
*** (1) WAITING FOR THIS LOCK TO BE GRANTED:
RECORD LOCKS space id 42 page no 3 n bits 72 index PRIMARY of table `shop`.`users` 
trx id 1001 lock_mode X gap before rec insert intention waiting

*** (2) HOLDS THE LOCK(S):
RECORD LOCKS space id 42 page no 3 n bits 72 index PRIMARY of table `shop`.`users` 
trx id 1002 lock_mode X locks gap before rec
```

**"분명히 데이터가 아무것도 없어서 잠글 레코드(Record)조차 없었는데, 도대체 누구와 무엇을 두고 데드락(Deadlock)이 걸린 거지?!"**  
게다가 두 쿼리는 서로 다른 유저 ID(`15`번과 `18`번)를 다루고 있었습니다! 서로 다른 번호인데 왜 충돌이 난 걸까요?

---

## 2. 주차장 돗자리 비유: 유령을 막으려다 터지는 비극

MySQL의 기본 스토리지 엔진인 **InnoDB**는 기본 트랜잭션 격리 수준으로 **Repeatable Read (RR)**를 사용합니다.  
RR 격리 수준의 핵심 사명은 **"트랜잭션 도중에 없던 데이터가 갑자기 유령처럼 나타나는 유령 읽기(Phantom Read)를 절대 허용하지 않는 것"**입니다.

이를 주차장에 비유해 봅시다:
- 현재 주차장에 **10번**과 **20번** 자리에만 차가 주차되어 있습니다. 11번부터 19번까지는 **텅 빈 공간(Gap)**입니다.
- **운전자 A (트랜잭션 1)**가 15번 자리에 차를 대려고 들어왔습니다.
- A는 "내가 15번에 차를 댈 건데, 다른 사람이 10번과 20번 사이에 끼어들면 안 돼!"라며 **10번과 20번 사이의 텅 빈 공간 전체에 돗자리를 쫘악 폅니다.** 이것이 바로 **갭 락(Gap Lock)**입니다!
- 뒤이어 **운전자 B (트랜잭션 2)**가 18번 자리에 차를 대려고 들어왔습니다.
- B도 18번 자리를 확인하더니 10번과 20번 사이 빈 공간에 돗자리를 폅니다.
- **놀라운 사실!** InnoDB에서 **갭 락은 순수한 방어용 잠금**이기 때문에, 돗자리 위에 다른 사람이 돗자리를 겹쳐 까는 것을 허용합니다(Shared 성격). 따라서 A와 B는 둘 다 성공적으로 돗자리를 깝니다!
- **참사의 순간 (INSERT 시도)**:
  1. A가 15번에 차를 집어넣으려고 합니다(**Insert Intention Lock**). 하지만 B의 돗자리가 깔려 있어서 차를 못 넣고 **B가 돗자리를 치울 때까지 대기(Wait)**합니다!
  2. B가 18번에 차를 집어넣으려고 합니다. 하지만 이번엔 A의 돗자리가 깔려 있어서 **A가 돗자리를 치울 때까지 대기(Wait)**합니다!
  3. **"네가 먼저 돗자리 치워!" vs "너부터 치워!"** 두 운전자는 차 시동을 건 채 서로 멱살을 잡고 영원히 대기하게 됩니다!
  4. 주차장 관리인(InnoDB Deadlock Detector)이 출동하여 B의 차를 강제로 견인(Rollback)해 버리고 나서야 A가 주차할 수 있게 됩니다!

---

## 3. 핵심 아키텍처 및 요구사항

당신은 MySQL InnoDB 스토리지 엔진의 인덱스 슬롯, 갭 분할, 트랜잭션 격리수준(RR vs RC), 레코드 락(Record Lock), 갭 락(Gap Lock), 넥스트 키 락(Next-Key Lock), 인서트 인텐션 대기 및 Wait-For Graph 기반 데드락 감지 엔진을 시뮬레이션해야 합니다.

### 1) 테이블 인덱스 초기화 (`INIT`)
- `INIT <keys>`
  - 정수형 Primary Key 목록을 쉼표(`,`)로 구분하여 오름차순으로 테이블에 적재합니다. (예: `INIT 10,20,30`)
  - 출력: `INIT_OK keys=[<keys>] gaps=[<gaps>]`
  - 갭(Gap) 구간 표기:
    - 첫 키 이전: `(-inf, first_key)`
    - 키와 키 사이: `(key_i, key_i+1)`
    - 마지막 키 이후: `(last_key, +inf)`
    - 예: `keys=[10, 20, 30]`, `gaps=[(-inf, 10), (10, 20), (20, 30), (30, +inf)]`

### 2) 트랜잭션 시작 (`BEGIN`)
- `BEGIN <tx_id> <RR|RC>`
  - `<tx_id>` 트랜잭션을 시작합니다. 격리 수준은 `RR` (Repeatable Read) 또는 `RC` (Read Committed)입니다.
  - 출력: `BEGIN_OK tx=<tx_id> isolation=<iso>`

### 3) 잠금 조회 (`SELECT_FOR_UPDATE`)
- **단건 조회**: `SELECT_FOR_UPDATE <tx_id> <key>`
  - 키가 테이블에 이미 존재하는 경우:
    - `RR`, `RC` 모드 모두 해당 키에 **레코드 락(REC_LOCK)**을 획득합니다.
  - 키가 테이블에 존재하지 않는 경우:
    - **`RR` 모드**: 키가 속한 갭 구간에 **갭 락(GAP_LOCK)**을 획득합니다.
    - **`RC` 모드**: 갭 락이 비활성화되어 있으므로 어떤 락도 획득하지 않습니다 (`locks=[]`).
- **범위 조회**: `SELECT_FOR_UPDATE <tx_id> <start_key> <end_key>`
  - `start_key <= key <= end_key` 범위에 있는 기존 모든 키에 **레코드 락(REC_LOCK)**을 획득합니다.
  - **`RR` 모드**: `[start_key, end_key]` 구간과 교차(intersect)하는 모든 갭 구간에 대해 **갭 락(GAP_LOCK)**을 획득합니다.
  - **`RC` 모드**: 레코드 락만 획득하며 갭 락은 일절 획득하지 않습니다.
- 출력: `LOCK_ACQUIRED tx=<tx_id> locks=[<lock1>, <lock2>, ...]`

### 4) 데이터 삽입 (`INSERT`)
- `INSERT <tx_id> <key>`
  - 이미 존재하는 키라면: `ERROR:KEY_ALREADY_EXISTS key=<key>` 출력.
  - 키가 들어갈 갭 구간을 찾습니다.
  - **대기 조건**: 다른 활성/블록 트랜잭션 중 해당 갭 구간에 **갭 락(GAP_LOCK)**을 보유하고 있는 트랜잭션이 있다면 삽입할 수 없습니다!
    - 해당 트랜잭션은 `BLOCKED` 상태가 되며, 첫 번째로 발견된 방해 트랜잭션에 대해 대기(`waiting_for`)합니다.
    - **데드락 감지 (Wait-For Graph)**:
      - 대기 관계를 형성했을 때 사이클(예: `tx1 -> tx2 -> tx1`)이 발생하는지 검사합니다.
      - 사이클이 감지되면 현재 삽입을 시도한 트랜잭션(`<tx_id>`)이 희생자(Victim)로 선정되어 즉시 **자동 롤백(Rollback)**됩니다.
      - 롤백 시 보유 중이던 모든 락과 이미 INSERT했던 키들이 취소되며, 이로 인해 대기 중이던 다른 트랜잭션이 깨어날 수 있습니다.
      - 출력:
        ```text
        ERROR:DEADLOCK_DETECTED victim=<tx_id> rollback=TRUE
        STATUS:UNBLOCKED_INSERTED tx=<unblocked_tx> key=<key> (깨어난 트랜잭션이 있다면)
        ```
    - 데드락이 아니라면 단순 대기:
      - 출력: `LOCK_WAIT tx=<tx_id> waiting_gap=<gap> blocked_by=<holder_tx>`
  - 방해하는 갭 락이 없다면 즉시 삽입 성공:
    - 테이블 키 목록에 추가되고 정렬됩니다.
    - 출력: `INSERT_OK tx=<tx_id> key=<key>`

### 5) 커밋 (`COMMIT`) & 롤백 (`ROLLBACK`)
- `COMMIT <tx_id>`
  - 트랜잭션이 정상 완료되며 보유 중이던 모든 레코드 락과 갭 락이 해제됩니다.
  - 출력:
    ```text
    COMMIT_OK tx=<tx_id> released_locks=<count>
    STATUS:UNBLOCKED_INSERTED tx=<unblocked_tx> key=<key> (깨어난 트랜잭션이 있다면 순차 출력)
    ```
- `ROLLBACK <tx_id>`
  - 트랜잭션이 취소되며, 해당 트랜잭션이 삽입했던 모든 키가 롤백되고 모든 락이 해제됩니다.
  - 출력:
    ```text
    ROLLBACK_OK tx=<tx_id>
    STATUS:UNBLOCKED_INSERTED tx=<unblocked_tx> key=<key> (깨어난 트랜잭션이 있다면 순차 출력)
    ```
- 트랜잭션이 존재하지 않거나 이미 종료된 경우: `ERROR:TRANSACTION_INACTIVE tx=<tx_id>`

### 6) 상태 요약 (`STATS`)
- `STATS`
  - 현재 테이블 키 목록, 활성/대기 트랜잭션 수, 총 발생한 데드락 횟수를 출력합니다.
  - 출력: `STATS keys=[<keys>] active_txs=<active> blocked_txs=<blocked> deadlocks=<deadlock_count>`

---

## 4. 실무 권장 아키텍처 및 교훈

1. **실무 테크 기업(카카오, 토스, 쿠팡 등)이 격리 수준을 `READ COMMITTED (RC)`로 설정하는 이유**:
   - MySQL InnoDB의 기본값은 `REPEATABLE READ (RR)`이지만, 대규모 트래픽 환경에서는 갭 락(Gap Lock)과 넥스트 키 락(Next-Key Lock)으로 인한 **원인 모를 동시성 저하 및 빈번한 데드락**이 서비스 장애의 주범이 됩니다.
   - 격리 수준을 `READ COMMITTED`로 낮추면 Gap Lock이 대부분 비활성화되어(외래키 검사 등 특수 목적 제외) 동시 처리량이 비약적으로 증가합니다.
2. **`binlog_format=ROW` 필수 연동**:
   - RC 격리 수준에서는 팬텀 리드나 순서 뒤바뀜이 발생할 수 있으므로, 복제(Replication) 정합성을 위해 반드시 Binary Log 포맷을 문장 기반(`STATEMENT`)이 아닌 행 기반(`ROW`)으로 설정해야 합니다.
3. **존재하지 않는 키에 대한 `SELECT ... FOR UPDATE` 지양**:
   - 없는 키를 선점하려고 비관적 락을 걸면 광범위한 갭 락이 발생하여 주변 키의 모든 INSERT를 올스톱시킵니다.
   - 중복 방지는 `UNIQUE KEY` 제약조건과 `INSERT ... ON DUPLICATE KEY UPDATE` 또는 분산 락(Redis Redlock)을 활용하는 것이 훨씬 안전합니다.
