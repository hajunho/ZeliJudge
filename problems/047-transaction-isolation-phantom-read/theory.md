# 유령의 습격: 트랜잭션 격리 수준(Isolation Level)과 팬텀 리드(Phantom Read)

> "트랜잭션을 걸었다는 사실만으로 동시성 버그에서 안전하다고 믿는 것은,  
> 방화벽을 켜두었으니 모든 해킹을 다 막았다고 믿는 것과 같다."

---

## 1. 현실 세계 비유: 콘서트장 객석 요원과 비상구 관객

100석 한정 특별 콘서트장 입구를 관리하는 상황을 상상해 보세요.

```text
❌ 반복 읽기 (Repeatable Read)의 함정:
   안전요원 A가 객석을 둘러보며 수량을 셉니다.
   "현재 98명! 아직 2자리 남았으니 티켓 2장을 마저 발급하겠습니다."
   그런데 그 찰나, 반대편 비상구에서 안전요원 B가 손님 2명을 들여보내고 문을 잠갔습니다(COMMIT).
   안전요원 A는 자기 트랜잭션이 시작될 때 찍어둔 사진(MVCC 스냅샷)만 보고 있으므로,
   새로 들어온 손님을 보지 못하고 여전히 "아직 98명이네" 하며 손님 2명을 추가로 들여보냅니다.
   결과 -> 100석 콘서트장에 102명이 입장하여 압사 사고(오버부킹, Overbooking) 발생!

✅ 직렬화 가능 (Serializable)의 철벽 방어:
   안전요원 A가 객석을 세는 동안, 객석으로 통하는 모든 비상구와 복도에 자물쇠(Next-Key Lock)를 채웁니다.
   안전요원 B가 문을 열고 손님을 밀어 넣으려 하자마자 자물쇠 경보(Serialization Conflict)가 울리며 입장이 차단됩니다!
   결과 -> 정원 100명 완벽 준수!
```

---

## 2. ANSI SQL 4대 격리 수준과 3대 이상 현상(Anomaly)

데이터베이스 표준은 동시성과 데이터 일관성 사이의 트레이드오프에 따라 4가지 격리 수준을 정의합니다.

| 격리 수준 (Isolation Level) | Dirty Read (더티 리드) | Non-Repeatable Read (반복 불가능 읽기) | Phantom Read (유령 읽기) | 특징 및 동시성 처리량 |
| :--- | :---: | :---: | :---: | :--- |
| **Read Uncommitted** | ❌ 발생 | ❌ 발생 | ❌ 발생 | 커밋 안 된 남의 데이터도 읽음 (실무 사용 금지) |
| **Read Committed** (Oracle, PG 기본) | ✅ 방어 | ❌ 발생 | ❌ 발생 | 커밋된 것만 읽지만, 쿼리 도중 다른 트랜잭션이 수정하면 값이 바뀜 |
| **Repeatable Read** (MySQL 기본) | ✅ 방어 | ✅ 방어 | ❌ 발생 (일반 SELECT 시) | 트랜잭션 시작 시점의 스냅샷을 읽음. 신규 행 삽입(INSERT) 시 팬텀 발생 |
| **Serializable** | ✅ 방어 | ✅ 방어 | ✅ 방어 | 모든 읽기에 넥스트 키 락을 걸어 직렬화. 완벽하지만 처리량 급감 |

---

## 3. MVCC(다중 버전 동시성 제어)와 Undo Log의 비밀

MySQL InnoDB나 PostgreSQL 같은 현대적 RDBMS는 성능을 위해 **"읽는 자는 쓰는 자를 막지 않고, 쓰는 자는 읽는 자를 막지 않는다"**는 MVCC를 사용합니다.

```mermaid
flowchart LR
    subgraph Table [실제 테이블 데이터]
        Row1[Item 1]
        Row2[Item 2]
    end

    subgraph UndoLog [언두 로그 Undo Log]
        OldVer[과거 커밋 버전 스냅샷]
    end

    subgraph TxA [트랜잭션 A (Repeatable Read)]
        ReadA[SELECT count: 2개로 보임]
    end

    subgraph TxB [트랜잭션 B]
        InsertB[INSERT Item 3 -> COMMIT]
    end

    InsertB -->|테이블에 3번째 행 추가| Table
    TxA -->|스냅샷 뷰 조회| UndoLog
    OldVer -.-> ReadA
```

### 왜 Repeatable Read에서 오버부킹이 터지는가?
1. 트랜잭션 A가 `SELECT count(*) WHERE item = 'TICKET'`을 실행합니다 $\to$ 98건 반환.
2. 트랜잭션 B가 몰래 `INSERT INTO tickets ...`를 2건 날리고 `COMMIT`합니다 $\to$ 실제 테이블은 100건이 됨.
3. 트랜잭션 A가 다시 `SELECT count(*)`를 실행합니다.
   - InnoDB는 트랜잭션 A의 시작 시점 스냅샷(Undo Log)을 보여주므로 **여전히 98건**으로 보입니다!
4. 트랜잭션 A는 "아직 2자리 남았네!" 하고 `INSERT INTO tickets ...`를 날려 커밋해버립니다.
5. 결국 테이블에는 총 **102건**이 들어가며 회사 규정을 위반하는 치명적인 오버부킹 사고가 터집니다!

---

## 4. 해결책: 넥스트 키 락(Next-Key Lock)과 비관적 락

일반적인 `SELECT`는 락을 전혀 걸지 않는 **Consistent Nonlocking Read(스냅샷 읽기)**입니다.  
따라서 팬텀 리드를 막고 동시성 수량을 안전하게 통제하려면 반드시 **락을 동반한 현재 읽기(Locking Current Read)**를 써야 합니다.

### 1. `SELECT ... FOR UPDATE` (비관적 락)
```sql
START TRANSACTION;
-- 행뿐만 아니라 행과 행 사이의 빈 공간(Gap)까지 락을 걸어 다른 트랜잭션의 INSERT를 차단!
SELECT count(*) FROM tickets WHERE event_id = 1 FOR UPDATE;

-- 수량 검증 후 안전하게 발급
INSERT INTO tickets (event_id, user_id) VALUES (1, 'user123');
COMMIT;
```
- **Record Lock**: 이미 존재하는 인덱스 레코드에 거는 배타락.
- **Gap Lock**: 레코드와 레코드 사이의 빈 공간에 다른 트랜잭션이 새 데이터를 INSERT하지 못하게 막는 락.
- **Next-Key Lock**: Record Lock + Gap Lock의 조합. InnoDB가 팬텀 리드를 방어하는 핵심 무기입니다.

---

## 5. 실무 대규모 선착순 티켓팅 아키텍처 3대 모범 패턴

1. **Redis 원자적 카운터 (가장 추천)**:
   - DB에 트랜잭션과 락을 걸면 수만 명이 몰릴 때 DB CPU가 100%를 찍고 뻗습니다.
   - Redis의 `INCR` 또는 Lua 스크립트를 사용하여 인메모리에서 `0.001초` 만에 선착순 100명을 먼저 자르고, 성공한 100명만 비동기 메시지 큐(Kafka/RabbitMQ)를 통해 DB에 영구 저장합니다.
2. **비관적 락 + 부모 테이블 잠금**:
   - `events` 테이블의 해당 이벤트 행(`id=1`)에 `SELECT ... FOR UPDATE`를 걸어 단일 행 배타락으로 전체 발급 과정을 직렬화합니다.
3. **유니크 제약조건(Unique Key) 활용**:
   - `(event_id, seat_number)`에 유니크 인덱스를 걸어두면, 두 트랜잭션이 동시에 같은 번호를 발급하려 할 때 DB가 `Duplicate Key Exception`을 뿜으며 1명을 안전하게 튕겨냅니다.

---

## 6. 요약

> 1. `Repeatable Read`는 스냅샷 덕분에 읽기는 일관되지만, **보이지 않는 유령 행(Phantom)으로 인해 한도 초과 오버부킹**이 발생할 수 있다.
> 2. 팬텀 리드를 완벽히 차단하려면 **`SERIALIZABLE` 격리 수준**이나 **`SELECT ... FOR UPDATE` 넥스트 키 락**을 사용해야 한다.
> 3. 대규모 선착순 시스템에서는 DB 락 대신 **Redis 원자적 카운터 + 비동기 큐**를 사용하는 것이 실무 표준이다.
