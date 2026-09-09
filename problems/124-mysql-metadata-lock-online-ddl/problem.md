# 124. DB에 컬럼 하나 추가했을 뿐인데 왜 10초 만에 전사 커넥션이 폭사해요?!: MySQL 메타데이터 락(Metadata Lock, MDL) 큐 블로킹과 고스트(gh-ost) 온라인 DDL 알고리즘

## 문제 설명

스타트업의 주니어 백엔드 개발자 젤리(Zeli)는 신규 프로모션 기능을 배포하기 위해 `orders`(주문) 테이블에 `promo_code` 컬럼을 추가하는 DDL을 준비했습니다:
```sql
ALTER TABLE orders ADD COLUMN promo_code VARCHAR(50);
```

개발 DB(로컬 Docker)에서 테스트했을 때는 데이터가 100건밖에 없어 **단 0.01초** 만에 성공했습니다.  
자신감을 얻은 젤리는 트래픽이 몰리는 평일 오후 2시, 운영 DB 콘솔에서 동일한 `ALTER TABLE` 명령어를 실행했습니다.

그런데 엔터를 누른 지 5초도 지나지 않아 사내 슬랙에 전사 장애 경보가 울려 퍼졌습니다! 🚨
- *"결제 서버 타임아웃 발생! 504 Gateway Timeout 폭증!"*
- *"로그인 안 됨! 장바구니 조회 안 됨! 메인 페이지 올스톱!"*
- *"스프링 부트 HikariCP 커넥션 풀 고갈: `ConnectionTimeoutException: Timeout after 30000ms`!"*

DB 모니터링 대시보드를 열어보니 활성 커넥션 수가 한계치(`max_connections = 500`)까지 치솟았고, 수백 개의 쓰레드가 다음 메시지를 띄우며 영구 동결되어 있었습니다:
```
Waiting for table metadata lock
```

---

### 왜 이런 참사가 발생할까? (MDL 대기 큐의 EXCLUSIVE 우선순위 역설)

MySQL InnoDB는 데이터 행(Row) 수준의 동시성을 보장하지만, 트랜잭션 도중 테이블 스키마가 마음대로 바뀌는 것을 방지하기 위해 **메타데이터 락(Metadata Lock, MDL)** 메커니즘을 사용합니다:
- `SELECT`, `INSERT`, `UPDATE`, `DELETE` (DML): 테이블에 **`SHARED` MDL** 락을 획득. (여러 트랜잭션이 동시 획득 가능)
- `ALTER TABLE`, `DROP TABLE` (DDL): 테이블에 **`EXCLUSIVE` MDL** 락을 획득. (다른 어떤 락과도 공존 불가)

**가장 치명적인 사실은 MDL 락이 쿼리가 끝날 때가 아니라 트랜잭션이 `COMMIT` 또는 `ROLLBACK`될 때까지 유지된다는 점입니다.**

1. **선행 롱 트랜잭션 존재**:  
   백그라운드에서 실행 중이던 정산 배치 쿼리가 `SHARED` 락을 쥐고 아직 커밋되지 않은 상태였습니다.
2. **DDL의 대기 큐 진입**:  
   젤리의 `ALTER TABLE`은 `EXCLUSIVE` 락을 요구하지만, 선행 트랜잭션이 끝나지 않아 락을 얻지 못하고 **MDL 대기 큐(Wait Queue)**에 진입합니다.
3. **후속 일반 쿼리의 연쇄 블로킹 (The Blocker Paradox)**:  
   MySQL의 MDL 대기 큐는 `EXCLUSIVE` 요청의 기아(Starvation)를 방지하기 위해 **후속 `SHARED` 요청보다 `EXCLUSIVE` 대기자에게 우선순위**를 부여합니다.  
   즉, **"큐에 `EXCLUSIVE` 대기자가 하나라도 있으면, 그 뒤에 들어오는 모든 신규 `SELECT`와 `INSERT`는 앞선 DDL을 추월하지 못하고 무조건 뒤에 줄을 서서 멈춰야 합니다!"**

```
[MySQL MDL 대기 큐의 연쇄 블로킹 대참사]

1. 현재 실행 중:
   [Tx 1: 정산 SELECT (SHARED)] ───► (10초 동안 커밋 안 됨)

2. MDL 대기 큐 (FIFO with Exclusive Priority):
   [대기 1번: ALTER TABLE (EXCLUSIVE)]  <── Tx 1 끝나길 대기
        ▲
        │ (추월 불가! 뒤에 줄서기 강제)
   [대기 2번: 유저 로그인 SELECT (SHARED)]   <── 블로킹!
   [대기 3번: 주문 결제 INSERT (SHARED)]    <── 블로킹!
   [대기 4번: 장바구니 UPDATE (SHARED)]    <── 블로킹!
   ... (초당 수백 개 쿼리가 줄줄이 동결!)
```

결과적으로 단 하나의 롱 트랜잭션 때문에 수천 건의 정상 트랜잭션이 커넥션을 반납하지 못한 채 큐에 묶여 대기하게 되고, 1~2초 만에 DB 커넥션 풀(`max_connections`)이 100% 고갈되어 전사 시스템이 뻗어버리는 것입니다.

---

### 구원 투수: GitHub `gh-ost` 온라인 DDL 알고리즘

이 문제를 해결하기 위해 GitHub이 개발한 오픈소스 도구인 **`gh-ost` (GitHub's Online Schema Migrations)**는 원본 테이블에 직접 `ALTER TABLE`을 걸지 않고 다음과 같은 **4단계 무중단 온라인 마이그레이션**을 수행합니다:

1. **섀도우 테이블 생성**: 원본 테이블 스키마에 신규 컬럼을 반영한 임시 테이블(`_orders_gho`)을 생성합니다.
2. **청크 단위 백그라운드 데이터 복사 (Backfill)**: 원본 데이터를 일정 단위(`chunk_size`, 예: 100건)로 나누어 초단기 트랜잭션으로 복사합니다. 긴 락이 전혀 발생하지 않습니다.
3. **실시간 델타 반영 (Delta Binlog Replay)**: 복사 도중 원본 테이블에 발생하는 `INSERT/UPDATE/DELETE`를 바이너리 로그(Binlog) 스트림으로 캡처하여 섀도우 테이블에 실시간 동기화합니다.
4. **찰나의 원자적 테이블 맞교환 (Atomic Cutover)**: 복제 지연이 0이 되면, `RENAME TABLE orders TO _orders_old, _orders_gho TO orders;`를 단 0.001초 만에 실행하여 무중단으로 스키마 변경을 완료합니다.

---

## 과제

당신은 MySQL의 메타데이터 락(MDL) 큐잉 동작과 `gh-ost` 온라인 DDL의 성능 차이를 검증하는 **"MDL 시뮬레이터"**를 구현해야 합니다.

### 입력 형식 (JSON)

표준 입력(stdin)으로 다음 JSON 객체가 주어집니다:
- `mode`: `"NAIVE_DDL"` (전통적 직접 ALTER TABLE) 또는 `"GHOST_DDL"` (gh-ost 무중단 온라인 DDL)
- `config`:
  - `max_connections`: DB 커넥션 풀 최대 크기 (정수 $\ge 1$)
  - `lock_wait_timeout`: MDL 락 대기 타임아웃 (초, 정수 $\ge 1$). 대기 큐에서 이 시간 이상 기다리면 락 획득을 포기하고 `LOCK_WAIT_TIMEOUT` 발생.
  - `chunk_size`: `gh-ost` 모드에서 한 번에 복사하는 데이터 건수 (정수 $\ge 1$)
- `initial_rows`: 초기 원본 테이블 행 수 (정수 $\ge 0$)
- `timeline`: 시간순으로 주어지는 이벤트 배열. 각 이벤트:
  - `time`: 이벤트 발생 시점 ($t \ge 0$)
  - `action`: `"START_LONG_TX"` | `"ALTER_TABLE"` | `"USER_QUERY"`
  - `tx_id`: 고유 트랜잭션 식별자 (문자열)
  - `duration`: 락 획득 후 실행에 소요되는 시간 (초, 정수 $\ge 1$, 기본값 1)
  - `type`: `USER_QUERY`일 때 `"SELECT"` | `"INSERT"` | `"UPDATE"` | `"DELETE"` (기본값 `"SELECT"`)
  - `row_delta`: (선택) 커밋 시 테이블 행 수 변경분. 생략 시 INSERT는 +1, DELETE는 -1, 그 외는 0.

### 시뮬레이션 규칙 ($t = 0, 1, 2, \dots$)

매 시점 $t$마다 다음 순서로 처리됩니다:
1. **완료 트랜잭션 회수**:
   - 실행 중인 트랜잭션 중 종료 시점($finish\_time \le t$)에 도달한 작업은 커넥션과 락을 반납하고 `"COMMITTED"` 상태가 됩니다.
   - DDL이 성공하면 `schema_version = 2`가 되며, DML 커밋 시 `final_rows`에 `row_delta`가 누적됩니다.
2. **대기 큐 승급 (Lock Granting)**:
   - 현재 `EXCLUSIVE` 락 보유자가 없다면:
     - 큐 맨 앞이 `EXCLUSIVE`이고 현재 `SHARED` 보유자가 0명이면 `EXCLUSIVE` 락을 획득하고 실행을 시작합니다.
     - 큐 맨 앞이 `SHARED`이면, 연속된 모든 `SHARED` 요청들이 일제히 락을 획득하고 동시 실행을 시작합니다 (중간에 `EXCLUSIVE`를 만나면 중단).
3. **락 대기 타임아웃 검사**:
   - 여전히 큐에 남아있는 요청 중 `(t - enqueue_time) >= lock_wait_timeout`인 요청은 `"LOCK_WAIT_TIMEOUT"` 상태로 큐에서 제거되고 점유했던 커넥션을 반납합니다.
   - 타임아웃 발생으로 큐 맨 앞이 변경되었을 경우, 즉시 다시 2번(승급)을 시도합니다.
4. **신규 이벤트 처리**:
   - 시점 $t$에 도착한 이벤트들을 순서대로 처리합니다.
   - 만약 현재 활성 커넥션 수(`active_connections`)가 `max_connections` 이상이면 커넥션을 얻지 못하고 즉시 `"CONNECTION_POOL_EXHAUSTED"` 상태로 거부됩니다.
   - 커넥션 여유가 있다면 커넥션을 1개 할당받습니다:
     - **`NAIVE_DDL` 모드**:
       - `ALTER_TABLE`: `EXCLUSIVE` 락이 즉시 가능하면(보유자 0명, 큐 0개) 즉시 실행, 아니면 대기 큐 진입.
       - `USER_QUERY` / `START_LONG_TX`: `EXCLUSIVE` 락 보유자가 없고 **대기 큐에 대기 중인 `EXCLUSIVE` 요청도 없으며** 큐가 비어있으면 즉시 `SHARED` 락을 얻어 동시 실행, 그렇지 않으면 대기 큐 진입.
     - **`GHOST_DDL` 모드**:
       - `ALTER_TABLE`: 메인 테이블에 EXCLUSIVE 락을 걸지 않고 백그라운드 워커로 실행됩니다 (커넥션 1개 점유).
         - 총 청크 수 $C = \max(1, \lceil initial\_rows / chunk\_size ceil)$
         - 총 소요 시간 = $C + 1$초 ($C$초간 백그라운드 청크 복사 + 1초간 원자적 컷오버)
         - 완료 시 `schema_version = 2`가 되고 커넥션을 반납합니다.
       - `USER_QUERY` / `START_LONG_TX`: DDL이 백그라운드에서 돌고 있으므로 일반 쿼리들은 메인 테이블에서 아무런 방해 없이 `SHARED` 락을 얻어 즉시 실행됩니다.

---

### 출력 형식 (JSON)

결과를 표준 출력(stdout)으로 JSON 형식(들여쓰기 2칸)으로 출력합니다:
```json
{
  "mode": "NAIVE_DDL",
  "summary": {
    "total_requests": 7,
    "committed": 4,
    "lock_wait_timeouts": 1,
    "connection_pool_exhaustions": 2,
    "max_concurrent_connections_used": 5,
    "final_rows": 501,
    "schema_version": 1
  },
  "query_results": [
    {
      "tx_id": "tx_batch",
      "action": "START_LONG_TX",
      "status": "COMMITTED",
      "start_time": 0,
      "finish_time": 5
    },
    {
      "tx_id": "ddl_col",
      "action": "ALTER_TABLE",
      "status": "LOCK_WAIT_TIMEOUT",
      "start_time": null,
      "finish_time": 4
    },
    {
      "tx_id": "q1",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 4,
      "finish_time": 5
    },
    {
      "tx_id": "q4",
      "action": "USER_QUERY",
      "status": "CONNECTION_POOL_EXHAUSTED",
      "start_time": null,
      "finish_time": 3
    }
  ]
}
```

---

## 입출력 예시

### 예시 1 (NAIVE_DDL - 롱 트랜잭션과 DDL 블로킹으로 인한 커넥션 풀 폭사)
**입력**:
```json
{
  "mode": "NAIVE_DDL",
  "config": {
    "max_connections": 5,
    "lock_wait_timeout": 3,
    "chunk_size": 100
  },
  "initial_rows": 500,
  "timeline": [
    {"time": 0, "action": "START_LONG_TX", "tx_id": "tx_batch", "duration": 5},
    {"time": 1, "action": "ALTER_TABLE", "tx_id": "ddl_col", "duration": 3},
    {"time": 2, "action": "USER_QUERY", "tx_id": "q1", "type": "SELECT", "duration": 1},
    {"time": 2, "action": "USER_QUERY", "tx_id": "q2", "type": "INSERT", "duration": 1},
    {"time": 3, "action": "USER_QUERY", "tx_id": "q3", "type": "SELECT", "duration": 1},
    {"time": 3, "action": "USER_QUERY", "tx_id": "q4", "type": "SELECT", "duration": 1},
    {"time": 3, "action": "USER_QUERY", "tx_id": "q5", "type": "SELECT", "duration": 1}
  ]
}
```

**출력**:
```json
{
  "mode": "NAIVE_DDL",
  "summary": {
    "total_requests": 7,
    "committed": 4,
    "lock_wait_timeouts": 1,
    "connection_pool_exhaustions": 2,
    "max_concurrent_connections_used": 5,
    "final_rows": 501,
    "schema_version": 1
  },
  "query_results": [
    {
      "tx_id": "tx_batch",
      "action": "START_LONG_TX",
      "status": "COMMITTED",
      "start_time": 0,
      "finish_time": 5
    },
    {
      "tx_id": "ddl_col",
      "action": "ALTER_TABLE",
      "status": "LOCK_WAIT_TIMEOUT",
      "start_time": null,
      "finish_time": 4
    },
    {
      "tx_id": "q1",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 4,
      "finish_time": 5
    },
    {
      "tx_id": "q2",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 4,
      "finish_time": 5
    },
    {
      "tx_id": "q3",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 4,
      "finish_time": 5
    },
    {
      "tx_id": "q4",
      "action": "USER_QUERY",
      "status": "CONNECTION_POOL_EXHAUSTED",
      "start_time": null,
      "finish_time": 3
    },
    {
      "tx_id": "q5",
      "action": "USER_QUERY",
      "status": "CONNECTION_POOL_EXHAUSTED",
      "start_time": null,
      "finish_time": 3
    }
  ]
}
```

---

### 예시 2 (GHOST_DDL - gh-ost 무중단 온라인 스키마 변경 구원)
**입력**:
```json
{
  "mode": "GHOST_DDL",
  "config": {
    "max_connections": 5,
    "lock_wait_timeout": 3,
    "chunk_size": 100
  },
  "initial_rows": 500,
  "timeline": [
    {"time": 0, "action": "START_LONG_TX", "tx_id": "tx_batch", "duration": 5},
    {"time": 1, "action": "ALTER_TABLE", "tx_id": "ddl_col", "duration": 3},
    {"time": 2, "action": "USER_QUERY", "tx_id": "q1", "type": "SELECT", "duration": 1},
    {"time": 2, "action": "USER_QUERY", "tx_id": "q2", "type": "INSERT", "duration": 1},
    {"time": 3, "action": "USER_QUERY", "tx_id": "q3", "type": "SELECT", "duration": 1},
    {"time": 3, "action": "USER_QUERY", "tx_id": "q4", "type": "SELECT", "duration": 1},
    {"time": 3, "action": "USER_QUERY", "tx_id": "q5", "type": "SELECT", "duration": 1}
  ]
}
```

**출력**:
```json
{
  "mode": "GHOST_DDL",
  "summary": {
    "total_requests": 7,
    "committed": 7,
    "lock_wait_timeouts": 0,
    "connection_pool_exhaustions": 0,
    "max_concurrent_connections_used": 5,
    "final_rows": 501,
    "schema_version": 2
  },
  "query_results": [
    {
      "tx_id": "tx_batch",
      "action": "START_LONG_TX",
      "status": "COMMITTED",
      "start_time": 0,
      "finish_time": 5
    },
    {
      "tx_id": "ddl_col",
      "action": "ALTER_TABLE",
      "status": "COMMITTED",
      "start_time": 1,
      "finish_time": 7
    },
    {
      "tx_id": "q1",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 2,
      "finish_time": 3
    },
    {
      "tx_id": "q2",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 2,
      "finish_time": 3
    },
    {
      "tx_id": "q3",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 3,
      "finish_time": 4
    },
    {
      "tx_id": "q4",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 3,
      "finish_time": 4
    },
    {
      "tx_id": "q5",
      "action": "USER_QUERY",
      "status": "COMMITTED",
      "start_time": 3,
      "finish_time": 4
    }
  ]
}
```
