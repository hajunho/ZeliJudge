# [CS 백서 #090] 10만 건 UPDATE 쳤더니 테이블이 왜 50GB로 부풀어요?!: PostgreSQL MVCC, 데드 튜플(Dead Tuple)과 진공 청소(Vacuum)의 비극

> **"테이블에 들어있는 회원 수는 딱 10만 명뿐인데, 디스크 용량이 50GB로 치솟더니 `SELECT` 쿼리 하나에 30초씩 걸려요!"**  
> PostgreSQL을 운영하는 백엔드 개발자들이 가장 당황하는 미스터리입니다.  
> MySQL(InnoDB)은 데이터를 수정할 때 제자리(In-Place)에서 덮어쓰고 이전 버전은 Undo 로그에 따로 보관하지만,  
> **PostgreSQL은 모든 행(Row)이 절대 수정되지 않는 불변 튜플(Immutable Tuple)** 로 동작하기 때문입니다.  
> 원인은 바로 단 하나의 잊혀진 트랜잭션이 **Autovacuum 청소부를 결박하여, 수천만 개의 시체(Dead Tuple)가 디스크를 뒤덮게 만든 테이블 블로트(Table Bloat)** 였습니다!

---

## 1. 현실 세계 비유: 지우개가 없는 도서관 필경사와 잠든 손님

중세 도서관에서 고객 장부를 관리하는 필경사가 있습니다.
- **필경사에게는 지우개가 없습니다 (PostgreSQL의 불변 튜플 철학)**.
- 손님이 주소를 바꿔달라고(UPDATE) 요청하면, 필경사는 기존 줄을 지우지 못합니다.
- 대신 **기존 줄에 빨간 펜으로 빗금을 긋고(사망 선고, `xmax`), 장부 맨 아래 빈칸에 새 주소를 새로 씁니다(신규 출생, `xmin`)**.

### (1) 청소부(Vacuum)의 역할
- 하루에 주소가 1만 번 바뀌면, 장부에 빗금 친 쓸모없는 줄(데드 튜플) 1만 개가 쌓여 장부 두께가 10배로 두꺼워집니다.
- 그래서 도서관에는 **청소부(Vacuum)** 가 있어서, 빗금 쳐진 옛날 줄들을 칼로 긁어내고 빈 공간을 확보하여 다음 글씨를 쓸 수 있게 만듭니다.

### (2) 비극의 시작: 장부를 펴놓고 잠든 손님 (Idle in Transaction)
어느 날 아침 9시, 한 손님(분석가 or 백엔드 스크립트)이 장부를 펼쳐놓고(BEGIN) 커피를 마시다가 의자에서 잠들어버렸습니다(`idle in transaction`).
- 낮 동안 수많은 손님들이 와서 주소를 10만 번 고쳤습니다.
- 장부에는 10만 개의 빗금 친 줄(Dead Tuple)이 쌓였고, 장부는 1,000페이지짜리 백과사전 크기로 부풀어 올랐습니다.
- 청소부가 출동해서 빗금 친 줄들을 지우려고 하자, 도서관장이 막아섭니다:
  > *"잠깐! 저기 아침 9시부터 엎드려 자고 있는 손님이 깨어나면, 아침 9시 시점의 장부를 읽을 권리(MVCC 스냅샷 격리)가 있다! 저 손님이 일어나서 퇴장(COMMIT)하기 전까지는, **단 한 줄의 빗금 친 글씨도 절대 지우지 마라!**"*
- 결국 청소부는 빗자루를 들고 멍하니 서 있어야 했고(`Vacuum Blocked`), 장부는 50GB 크기로 부풀어 올라 마침내 도서관 서가가 무게를 이기지 못하고 무너져 내립니다!

---

## 2. 컴퓨터 과학 원리: PostgreSQL MVCC의 내부 동작

### (1) 튜플 헤더의 핵심 메타데이터: xmin과 xmax

PostgreSQL의 모든 튜플(행)은 숨겨진 23바이트짜리 헤더를 가지며, 여기에 핵심 트랜잭션 ID가 기록됩니다:

| 필드 | 설명 |
| :--- | :--- |
| **`xmin`** | 이 튜플을 생성(INSERT)한 트랜잭션의 ID |
| **`xmax`** | 이 튜플을 삭제(DELETE)하거나 갱신(UPDATE)하여 쓸모없게 만든 트랜잭션 ID (살아있다면 0) |

```text
[초기 상태: TX 100이 Alice 등록]
Tuple 1: (xmin: 100, xmax: 0,   name: "Alice", age: 20) ◄── LIVE!

[TX 200이 Alice의 나이를 21로 UPDATE]
Tuple 1: (xmin: 100, xmax: 200, name: "Alice", age: 20) ◄── DEAD TUPLE (사망!)
Tuple 2: (xmin: 200, xmax: 0,   name: "Alice", age: 21) ◄── NEW LIVE TUPLE (최신)

[TX 300이 Alice의 나이를 22로 UPDATE]
Tuple 1: (xmin: 100, xmax: 200, name: "Alice", age: 20) ◄── DEAD TUPLE
Tuple 2: (xmin: 200, xmax: 300, name: "Alice", age: 21) ◄── DEAD TUPLE
Tuple 3: (xmin: 300, xmax: 0,   name: "Alice", age: 22) ◄── NEW LIVE TUPLE
```

- 보시다시피 1건의 데이터를 2번 UPDATE 했을 뿐인데, 디스크에는 **3개의 튜플**이 물리적으로 자리를 차지하고 있습니다!
- 이것이 PostgreSQL이 `UPDATE`를 **`DELETE + INSERT`** 로 처리한다고 부르는 이유입니다.

---

### (2) xmin_horizon (오래된 트랜잭션의 지평선)

Vacuum이 데드 튜플을 안전하게 청소(Reclaim)하려면 다음 조건을 만족해야 합니다:

$$\text{튜플의 } xmax < \text{xmin\_horizon} \quad (\text{여기서 } \text{xmin\_horizon} = \min(\text{현재 활성 상태인 모든 트랜잭션 ID}))$$

- 만약 시스템에 가장 오래된 활성 트랜잭션이 `TX 150`이라면, `xmax = 200`인 데드 튜플은 절대 청소할 수 없습니다.
- 왜냐하면 `TX 150`은 과거의 스냅샷을 바라보고 있으므로, `TX 200`에 의해 죽은 튜플 1을 여전히 읽어야 할 수도 있기 때문입니다!
- 따라서 **단 하나의 트랜잭션이라도 수 시간 동안 커밋하지 않고 열려 있으면(`idle in transaction`), 그 이후에 생성된 모든 데드 튜플의 청소가 전면 중단**됩니다.

---

### (3) 테이블 블로트 (Table Bloat)의 치명적 피해

1. **디스크 낭비**:
   - 10만 행짜리 테이블(수십 MB)이 50GB로 팽창하여 스토리지 풀(Full) 장애 유발.
2. **Full Table Scan 지연 1,000배 폭증**:
   - `SELECT * FROM users`를 실행하면, PostgreSQL은 유효한 10만 건뿐만 아니라 **이미 죽은 5,000만 건의 데드 튜플까지 디스크에서 전부 퍼 올려서 하나하나 살아있는지 검사**해야 합니다.
   - 캐시(Shared Buffers)가 오염되고 쿼리 속도가 수 밀리초에서 수십 초로 곤두박질칩니다.
3. **인덱스 블로트 (Index Bloat)**:
   - UPDATE가 일어날 때마다 B-Tree 인덱스에도 새 튜플을 가리키는 엔트리가 계속 추가되어 인덱스 파일 크기마저 수십 GB로 비대해집니다.

---

## 3. 실무 엔지니어의 트러블슈팅 & 골든 룰

1. **장기 미완료 트랜잭션(Idle In Transaction) 강제 종료 설정**:
   ```sql
   -- 트랜잭션이 열린 채 10분 이상 유휴 상태면 자동으로 세션을 끊어버림!
   SET idle_in_transaction_session_timeout = '60000'; -- 60초 (또는 10분)
   ```
2. **데드 튜플 및 블로트 모니터링 쿼리**:
   ```sql
   SELECT relname, n_live_tup, n_dead_tup,
          round(n_dead_tup * 100.0 / nullif(n_live_tup + n_dead_tup, 0), 2) AS dead_ratio
   FROM pg_stat_user_tables;
   ```
3. **VACUUM vs VACUUM FULL**:
   - `VACUUM`: 빈 공간을 재사용 가능하도록 내부 슬롯만 비웁니다 (OS에 디스크 용량을 반환하지는 않음, 무중단 실행).
   - `VACUUM FULL`: 테이블을 새로 만들어 살아있는 튜플만 복사하고 이전 테이블을 통째로 날립니다 (OS에 디스크 용량 완벽 반환, 단 **배타적 테이블 락(Exclusive Lock)** 이 걸려 서비스 올스톱).
