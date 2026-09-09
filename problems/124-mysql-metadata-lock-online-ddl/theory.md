# MySQL 메타데이터 락(Metadata Lock, MDL)과 고스트(gh-ost) 온라인 DDL 아키텍처

> **"개발 DB에서는 0.01초 만에 컬럼이 추가됐는데, 운영 DB에 `ALTER TABLE`을 날렸더니 3초 만에 전사 API가 마비되고 DB 커넥션 풀이 폭사했어요?!"**  
> 백엔드 엔지니어와 DBA가 운영 환경에서 가장 공포스러워하는 순간 중 하나는 대형 테이블에 스키마 변경(DDL)을 적용할 때 발생하는 **"메타데이터 락 큐 블로킹(MDL Queue Blocking)"** 참사입니다.

---

## 1. 메타데이터 락(Metadata Lock, MDL)이란 무엇인가?

MySQL InnoDB는 데이터 행(Row) 수준의 동시성을 보장하기 위해 행 레벨 락(Row-Level Lock)과 MVCC(다중 버전 동시성 제어)를 사용합니다.  
하지만 **"데이터를 읽고 있는 도중에 다른 사람이 테이블 구조(컬럼 타입, 인덱스)를 마음대로 바꿔버리면 어떻게 될까?"**라는 치명적인 문제가 발생합니다.

예를 들어:
1. 트랜잭션 A가 `SELECT price FROM orders WHERE id = 100;`을 읽기 시작합니다.
2. 트랜잭션 B가 `ALTER TABLE orders DROP COLUMN price;`를 실행하여 컬럼을 지워버립니다.
3. 트랜잭션 A가 다음 행을 읽으려 할 때 `price` 컬럼이 사라져 있어 메모리 충돌이나 정합성 파괴가 발생합니다!

이를 방지하기 위해 MySQL 5.5.3부터 테이블의 **메타데이터(스키마 정의)**를 보호하는 **Metadata Lock (MDL)** 메커니즘이 도입되었습니다.

```
[MySQL 락 계층 구조]
┌───────────────────────────────────────────────┐
│        Metadata Lock (MDL, 테이블 정의 보호)     │ <- DDL vs DML 일관성 보장
├───────────────────────────────────────────────┤
│        Table Lock (테이블 전체 잠금)             │
├───────────────────────────────────────────────┤
│        Row Lock (행 레벨 락: S-Lock, X-Lock)    │ <- 레코드 데이터 보호
└───────────────────────────────────────────────┘
```

---

## 2. MDL 락의 종류와 수명 주기 (Lifecycle)

MDL은 크게 두 가지 유형으로 나뉩니다:

| 락 유형 | 대상 작업 | 설명 | 호환성 (Compatibility) |
|---|---|---|---|
| **SHARED (공유 락)** | `SELECT`, `INSERT`, `UPDATE`, `DELETE` (DML) | 데이터 조회 및 변경 작업 시 획득 | 여러 SHARED 락끼리는 동시 획득 가능 (상호 호환) |
| **EXCLUSIVE (배타 락)** | `ALTER TABLE`, `DROP TABLE`, `OPTIMIZE` (DDL) | 테이블 스키마 변경 작업 시 획득 | 다른 어떤 SHARED나 EXCLUSIVE 락과도 공존 불가 |

### ⚠️ 가장 치명적인 함정: MDL 락의 유지 기간
많은 주니어 개발자들이 **"SELECT 쿼리가 끝나면 락이 바로 풀리겠지?"**라고 오해합니다.  
하지만 **MDL 락은 쿼리가 끝날 때 풀리는 것이 아니라, 해당 세션의 트랜잭션이 `COMMIT` 또는 `ROLLBACK`되어 완전히 끝날 때까지 유지**됩니다!

즉, 자동 커밋(`autocommit=1`)이 꺼져 있거나 스프링의 `@Transactional` 안에서 무거운 외부 API를 호출하느라 트랜잭션이 10초 동안 열려 있다면, 그 10초 내내 해당 테이블의 `SHARED` MDL 락이 잡혀 있는 것입니다.

---

## 3. 대참사의 근본 원인: MDL 대기 큐의 EXCLUSIVE 우선순위 역설

그렇다면 롱 트랜잭션 하나가 `SHARED` 락을 쥐고 있는 상태에서 `ALTER TABLE`을 날리면 왜 전사 서비스가 마비될까요?

### Step 1: DDL의 대기 큐 진입
- 트랜잭션 1 (정산 배치 쿼리): `SHARED` 락 획득 후 10초간 실행 중.
- 트랜잭션 2 (`ALTER TABLE`): `EXCLUSIVE` 락 요청. 하지만 트랜잭션 1이 끝나지 않았으므로 락을 얻지 못하고 **대기 큐(MDL Wait Queue)**에 진입.

### Step 2: 후속 일반 쿼리의 연쇄 블로킹 (The Bottleneck)
MySQL의 MDL 큐는 `EXCLUSIVE` 요청이 영원히 락을 얻지 못하는 **기아 현상(Writer Starvation)**을 방지하기 위해 다음과 같은 규칙을 갖습니다:
> **"큐에 EXCLUSIVE 락 요청이 대기 중이라면, 그 뒤에 도착하는 신규 SHARED 락 요청은 앞선 EXCLUSIVE 요청을 추월할 수 없으며 무조건 뒤에 줄을 서야 한다!"**

```
[MDL 대기 큐의 연쇄 블로킹 대참사]

1. 활성 실행 중:
   [Tx 1: 정산 SELECT (SHARED)] ───► (10초 동안 끝나지 않음)

2. MDL 대기 큐 (FIFO with Exclusive Priority):
   [대기 1번: ALTER TABLE (EXCLUSIVE)]  <── Tx 1이 끝날 때까지 대기
        ▲
        │ (추월 불가! 뒤에 줄서기)
   [대기 2번: 유저 로그인 SELECT (SHARED)]   <── 블로킹!
   [대기 3번: 주문 결제 INSERT (SHARED)]    <── 블로킹!
   [대기 4번: 장바구니 UPDATE (SHARED)]    <── 블로킹!
   ... (초당 수백 개 쿼리가 줄줄이 동결!)
```

### Step 3: 커넥션 풀(HikariCP) 고갈과 전사 다운
- 평상시 1ms 만에 끝나던 일반 유저들의 `SELECT`와 `INSERT` 쿼리가 전부 DDL 뒤에 묶여 대기 상태(`Waiting for table metadata lock`)가 됩니다.
- 톰캣이나 스프링 부트 서버의 HikariCP 커넥션 풀(예: 최대 100개)이 1~2초 만에 100% 꽉 차버립니다 (`Active: 100 / Total: 100`).
- 그 이후 들어오는 모든 유저 요청은 커넥션을 얻지 못하고 `ConnectionTimeoutException` (504 Gateway Timeout)을 뿜으며 전사 서비스가 마비됩니다!

---

## 4. 구원 투수: 고스트(gh-ost) 온라인 스키마 변경 아키텍처

이러한 참사를 방지하기 위해 GitHub 엔지니어링 팀은 **gh-ost (GitHub's Online Schema Migrations for MySQL)**를 개발했습니다. (Percona의 `pt-online-schema-change`와 유사하지만 더 진화된 방식)

gh-ost는 원본 테이블에 직접 무거운 `ALTER TABLE`을 걸지 않고, 다음과 같은 4단계 무중단 마이그레이션 파이프라인을 가동합니다:

```
[gh-ost 온라인 스키마 변경 프로세스]

1. 섀도우 테이블 생성:
   orders ───────────────► _orders_gho (신규 컬럼이 추가된 빈 테이블)

2. 청크 단위 백그라운드 데이터 복사 (Backfill):
   orders [1 ~ 1000] ───► _orders_gho (초단기 쿼리로 잘라서 복사)
   orders [1001 ~ 2000] ─► _orders_gho (CPU/부하 모니터링하며 완급 조절)

3. 실시간 변경분 추적 (Delta Binlog Stream):
   orders에 신규 INSERT/UPDATE/DELETE 발생
         │
         ▼
     MySQL Binlog ──────► gh-ost 리더 ──► _orders_gho에 실시간 반영

4. 찰나의 원자적 테이블 교체 (Atomic Cutover):
   RENAME TABLE orders TO _orders_del, _orders_gho TO orders;
   (단 0.001초 만에 완료되어 락 대기 0초 달성!)
```

### gh-ost의 핵심 메커니즘
1. **청크 단위 복사 (Chunked Read)**:
   - 전체 1억 건의 데이터를 한 번에 복사하지 않고, PK 범위 기준 1,000건씩 초단기 트랜잭션으로 잘라서 복사합니다.
   - 따라서 원본 테이블에 긴 락을 유발하지 않으며, 일반 유저 트래픽에 영향을 주지 않습니다.
2. **트리거 대신 Binlog 스트리밍 사용**:
   - 기존 `pt-online-schema-change`는 원본 테이블에 트리거(Trigger)를 걸어 변경분을 복제했습니다. 하지만 트리거는 쓰기 쿼리마다 추가 락 경합을 일으켜 운영 서버에 부담을 줍니다.
   - gh-ost는 MySQL의 **바이너리 로그(Binlog)**를 비동기로 읽어 섀도우 테이블에 반영하므로 원본 테이블 쓰기 성능에 오버헤드가 거의 없습니다.
3. **원자적 컷오버 (Atomic Cutover)**:
   - 복사가 100% 완료되고 복제 지연(Replication Lag)이 0이 되면, `RENAME TABLE` 단 한 줄로 원본 테이블과 섀도우 테이블을 맞바꿉니다.
   - 이 교체 작업은 수 밀리초 만에 끝나므로 서비스 중단 시간(Downtime)이 0초에 수렴합니다.

---

## 5. 실무 엔지니어의 핵심 교훈 및 체크리스트

1. **운영 DB에서 직접 `ALTER TABLE` 날리지 않기**:
   - 데이터가 수백만 건 이상이거나 초당 트래픽이 높은 테이블에서는 반드시 `gh-ost`나 `pt-online-schema-change` 같은 온라인 DDL 도구를 사용해야 합니다.
2. **DDL 실행 전 롱 트랜잭션 점검**:
   - `SELECT * FROM information_schema.innodb_trx;`로 오래 열려 있는 트랜잭션이 없는지 확인합니다.
3. **세션 락 대기 타임아웃 방어막 설정**:
   - 불가피하게 직접 DDL을 실행할 때는 반드시 세션 레벨에서 타임아웃을 짧게 설정합니다:
     ```sql
     SET lock_wait_timeout = 3; -- 3초 이상 락을 못 얻으면 즉시 포기
     ALTER TABLE orders ADD COLUMN promo_code VARCHAR(50);
     ```
   - 이렇게 하면 DDL이 3초 만에 실패하고 종료되므로, 후속 일반 쿼리들이 큐에 묶여 커넥션 풀이 폭사하는 대참사를 방지할 수 있습니다.
