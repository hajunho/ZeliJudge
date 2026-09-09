# #162 결제 완료 후 방금 쓴 글이 사라졌다고요?!: MySQL 비동기 복제 지연(Replication Lag)과 Read-Your-Own-Writes (RYOW) 세션 일관성 라우터 & GTID 추적 (MySQL Replication Lag: Read-Your-Own-Writes Session Consistency & GTID Routing)

## 1. 실무 장애 시나리오: "주문 결제 마쳤는데 '주문 내역 없음'이 떠서 고객들이 중복 결제 폭탄을 터뜨렸어요!"

글로벌 이커머스 및 콘텐츠 플랫폼 '젤리마켓'은 초당 수만 건의 읽기 쿼리를 분산 처리하기 위해 **MySQL Primary(쓰기 전용 1대)와 3대의 Read Replica(읽기 전용 `replica-1`, `replica-2`, `replica-3`)**로 데이터베이스 클러스터를 구성했습니다.

블랙 프라이데이 타임세일 이벤트 당일, 수많은 고객이 상품을 주문하고 결제를 완료했습니다:
1. 고객 A가 결제 버튼을 클릭: `POST /orders` $	o$ Primary DB에 주문 정보가 성공적으로 `INSERT` 커밋 완료 ($T=100	ext{ms}$, GTID `mysql-master:1001`).
2. 프론트엔드 웹 SPA는 결제 완료 후 즉시 주문 상세 페이지로 리다이렉트: `GET /orders/5001` ($T=110	ext{ms}$).
3. 애플리케이션의 일반 로드밸런서/데이터소스 라우터는 읽기 트래픽이므로 단순 라운드로빈 방식으로 `replica-1`에 쿼리를 전송했습니다.

```
                      [ Client (Customer A) ]
                           │             │
        1. POST /orders    │             │ 2. GET /orders/5001
           (Insert Order)  │             │    (Immediate Read Redirect)
                           ▼             ▼
                 ┌───────────────┐     ┌────────────────────────┐
                 │  Primary DB   │     │  Read Replica 1        │
                 │  (GTID: 1001) │     │  (Lagging: GTID 995)   │
                 └───────┬───────┘     └───────────┬────────────┘
                         │                         │
                         │ Async Binlog Sync       │ Query Returns:
                         │ (Delayed 200ms by I/O)  │ "ORDER NOT FOUND!" (STALE READ!)
                         ▼                         ▼
                 ┌──────────────────────────────────────────────┐
                 │ Customer Panics: "My money was deducted      │
                 │ but order is missing! Let me buy again!"     │
                 │ -> DOUBLE BILLING / SUPPORT TICKET EXPLOSION!│
                 └──────────────────────────────────────────────┘
```

그러자 서비스 전역에서 충격적인 대재앙이 터졌습니다:
- **`ORDER NOT FOUND` 참사**:
  - Primary에서 발생한 대규모 트래픽으로 인해 비동기 복제 스레드(Binlog Dump $	o$ Relay Log $	o$ SQL Applier)에 **200ms ~ 2,000ms의 복제 지연(Replication Lag)**이 발생했습니다.
  - 리다이렉트된 `replica-1`은 아직 GTID `1001` 트랜잭션을 재생(Replay)하지 못한 상태였기에, 고객 A에게 **"주문 내역이 존재하지 않습니다"**를 반환했습니다!
  - 결제 금액은 빠져나갔는데 주문이 없다고 뜬 고객들은 시스템 오류로 착각하고 결제 버튼을 3~4번 더 눌러 **대규모 중복 결제 사고**가 터졌습니다.
- **프로필 수정 및 비밀번호 변경 후 로그인 불가**:
  - 비밀번호를 변경한 고객이 즉시 로그인(`SELECT password_hash`)을 시도했으나, 슬레이브 노드가 이전 비밀번호 해시를 반환하여 "비밀번호 불일치" 5회 오류로 계정이 잠겨버렸습니다!

---

## 2. 주니어 엔지니어들의 위험천만한 임시방편과 실패

### 실패 1: "그냥 모든 SELECT를 무조건 Primary로 보내죠!" (`PRIMARY_ONLY`)
- 복제 지연을 피하겠다고 모든 읽기 쿼리를 Primary로 몰았더니, **Primary DB의 CPU가 100%를 찍고 커넥션 풀이 고갈**되어 정작 중요한 쓰기 결제 트랜잭션까지 전면 마비되었습니다. 수억 원을 들여 구축한 Read Replica 3대는 CPU 1%로 놀고 있었습니다.

### 실패 2: "글 쓴 사용자는 1초 동안만 Primary를 보게 시간(TTL) 쿠키를 굽죠!" (`RYOW_STICKY`)
- 글이나 주문을 작성한 사용자 세션에 1초짜리 스티키 윈도우(`sticky_window_ms = 1000`)를 부여하여 1초간 Primary로 보냈습니다.
- 하지만 타임세일 폭주로 **복제 지연이 2.5초로 치솟자, 1초가 지난 시점에 슬레이브로 넘어가 여전히 구버전 데이터를 읽는 Stale Read**가 다시 발생했습니다!
- 반대로 복제가 50ms 만에 끝난 상황에서도 1초 동안 Primary를 불필요하게 괴롭혀 DB 부하를 낭비했습니다.

---

## 3. 구원 아키텍처: Read-Your-Own-Writes (RYOW) & GTID 인과성 라우터

엔지니어링팀은 단순 시간 기반 휴리스틱을 폐기하고, MySQL의 **GTID (Global Transaction Identifier)** 기반 **Read-Your-Own-Writes (세션 인과적 일관성, Causal Consistency)** 라우터를 도입했습니다:

```
[ Primary DB Commit ]
Primary commits Transaction -> Generates GTID: 1001
Returns Commit GTID: 1001 to Client Session Token!

[ Client Session Context ]
User Session tracks: last_write_gtid = 1001

[ Intelligent GTID Router ]
When Client sends GET /orders/5001:
1. Router inspects all Read Replicas' executed_gtid_set:
   - replica-1: executed_gtid = 995  (Lagging: REJECT)
   - replica-2: executed_gtid = 1001 (Caught up: QUALIFIED!)
   - replica-3: executed_gtid = 1005 (Caught up: QUALIFIED!)
2. Router picks the Least-Loaded Qualified Replica (replica-2)!
3. Serves Fresh Read with 100% Consistency and ZERO Load on Primary!
4. If ALL replicas are lagging behind 1001:
   -> Safely Fallback to Primary for this specific request!
```

---

## 4. 구현 명세 및 동작 규칙

본 문제에서는 4가지 라우팅 정책을 시뮬레이션하고 평가하는 `MySQLReplicationEngine`을 구현해야 합니다.

### (1) 데이터베이스 및 복제 모델
- **Primary 노드**:
  - 모든 `WRITE` 이벤트는 Primary DB에 즉시 반영되며, 단조 증가하는 정수 `gtid` (1, 2, 3...)가 부여됩니다.
  - Primary의 동시 읽기 허용량(`primary_read_capacity`)을 초과하여 읽기 요청이 발생하면 `primary_overload_count`가 1씩 증가합니다.
- **Read Replica 노드**:
  - 설정된 복제본 목록(`replicas: ["replica-1", "replica-2", ...]`).
  - `REPLICATION_APPLY` 이벤트가 발생하면 해당 복제본은 Primary의 binlog를 대상 `gtid`까지 재생(Replay)하여 로컬 스토리지를 갱신하고 `executed_gtid`를 업데이트합니다.
- **사용자 세션 (Session Context)**:
  - 사용자가 `WRITE`를 성공하면 세션에 `last_write_time`, `last_write_gtid`, `written_keys`가 기록됩니다.

### (2) 4가지 라우팅 모드 (`router_mode`)
1. **`NAIVE_REPLICA` (단순 라운드로빈)**:
   - 세션 기록이나 지연 여부를 일절 검사하지 않고, 복제본들에게 단순 라운드로빈(`replica-1` $	o$ `replica-2` $	o$ ...)으로 읽기 요청을 전달합니다.
   - 복제가 지연된 복제본에 도달하면 `is_stale = true`가 발생합니다.
2. **`PRIMARY_ONLY` (전체 Primary 강제)**:
   - 모든 읽기 요청을 무조건 Primary로 전달합니다.
   - 데이터는 최신이지만 Primary 용량(`primary_read_capacity`) 초과 시 `primary_overload_count`가 폭증합니다.
3. **`RYOW_STICKY` (시간 기반 스티키 윈도우)**:
   - 사용자가 최근 쓰기를 수행한 후 경과 시간(`timestamp - last_write_time`)이 `sticky_window_ms` 이하이면 Primary로 라우팅합니다.
   - 윈도우 시간이 지나면 복제본으로 라운드로빈 라우팅합니다.
   - 복제 지연이 윈도우 시간보다 길면 윈도우 만료 후 여전히 `is_stale = true`가 터집니다.
4. **`RYOW_GTID` (GTID 기반 세션 일관성 라우터)**:
   - 사용자의 세션에 유효한 쓰기 기록(`last_write_gtid > 0`)이 있을 때:
     - `executed_gtid >= last_write_gtid` 조건을 만족하는 복제본(Qualified Replicas)들을 필터링합니다.
     - 조건을 만족하는 복제본이 1대 이상 존재하면: 그중 **현재까지 누적 읽기 횟수(`read_count`)가 가장 적은 노드**로 라우팅합니다 (동률 시 replica_id 오름차순).
     - **어떤 복제본도 아직 해당 GTID를 반영하지 못했다면**: 안전하게 **Primary로 폴백(Fallback)** 라우팅합니다.
   - 쓰기 기록이 없는 순수 조회자(Guest 등)의 경우:
     - 전체 복제본 중 `read_count`가 가장 적은 노드로 라우팅합니다.

### (3) Stale Read 판정 기준
- 읽기 요청을 보낸 사용자가 해당 키(`key`)를 이전에 직접 수정한 작성자(`written_keys`에 포함)인 경우:
  - 읽어온 값(`val`)이 현재 Primary의 최신 값과 다르면 **`is_stale = true` (Read-Your-Own-Writes 위반)**로 판정하고 `stale_reads` 카운트를 1 증가시킵니다.
  - 작성자가 아닌 제3자의 읽기는 최종 일관성(Eventual Consistency) 모델상 Stale Read로 집계하지 않습니다.

---

## 5. 입출력 형식

### 입력 형식 (JSON on `sys.stdin`)
```json
{
  "config": {
    "router_mode": "RYOW_GTID",
    "sticky_window_ms": 2000,
    "primary_read_capacity": 5
  },
  "initial_data": {
    "order:5001": "PENDING"
  },
  "replicas": ["replica-1", "replica-2"],
  "events": [
    { "type": "WRITE", "timestamp": 100, "user_id": "customer-1", "key": "order:5001", "val": "PAID" },
    { "type": "READ", "timestamp": 110, "user_id": "customer-1", "key": "order:5001" },
    { "type": "REPLICATION_APPLY", "timestamp": 150, "replica_id": "replica-1", "gtid": 1 },
    { "type": "READ", "timestamp": 160, "user_id": "customer-1", "key": "order:5001" }
  ]
}
```

### 출력 형식 (JSON on `sys.stdout`)
```json
{
  "summary": {
    "router_mode": "RYOW_GTID",
    "total_writes": 1,
    "total_reads": 2,
    "primary_reads": 1,
    "replica_reads": 1,
    "stale_reads": 0,
    "primary_overload_count": 0,
    "consistency_guaranteed": true
  },
  "replica_status": {
    "replica-1": {
      "executed_gtid": 1,
      "read_count": 1
    },
    "replica-2": {
      "executed_gtid": 0,
      "read_count": 0
    }
  },
  "results": [
    {
      "type": "WRITE",
      "timestamp": 100,
      "user_id": "customer-1",
      "key": "order:5001",
      "gtid": 1,
      "status": "COMMITTED"
    },
    {
      "type": "READ",
      "timestamp": 110,
      "user_id": "customer-1",
      "key": "order:5001",
      "routed_to": "primary",
      "routing_reason": "GTID_LAG_FALLBACK_PRIMARY (required gtid 1)",
      "served_gtid": 1,
      "val": "PAID",
      "is_stale": false
    },
    {
      "type": "REPLICATION_APPLY",
      "timestamp": 150,
      "replica_id": "replica-1",
      "current_gtid": 1,
      "applied_events": 1
    },
    {
      "type": "READ",
      "timestamp": 160,
      "user_id": "customer-1",
      "key": "order:5001",
      "routed_to": "replica-1",
      "routing_reason": "GTID_SATISFIED_REPLICA (replica-1)",
      "served_gtid": 1,
      "val": "PAID",
      "is_stale": false
    }
  ]
}
```
