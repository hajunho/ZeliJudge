# 129. 방금 쓴 글을 등록했는데 왜 목록에 안 보여요?!: DB 마스터-슬레이브 복제 지연(Replication Lag)과 Read-Your-Own-Writes 일관성 라우팅 알고리즘

## 문제 설명

이커머스/SNS 스타트업의 주니어 백엔드 엔지니어 젤리(Zeli)는 서비스 트래픽이 폭증하여 데이터베이스 CPU가 95%에 육박하자, 읽기 쿼리 부하 분산을 위해 **Master-Slave (Primary-Replica) 복제 아키텍처**를 구축했습니다.

- **Master DB**: 모든 쓰기 트랜잭션(`INSERT`, `UPDATE`, `DELETE`) 전담
- **Read Replica 1, 2**: 모든 조회 쿼리(`SELECT`)를 라운드로빈으로 분산 처리

배포 후 데이터베이스 CPU 사용률이 30%대로 뚝 떨어지자 젤리는 뿌듯해했습니다. 😊  
하지만 다음 날 아침, 고객센터(CS)에 이상하고 기괴한 버그 리포트들이 폭주하기 시작했습니다! 🚨

- *"마이페이지에서 프로필 닉네임을 변경하고 '저장'을 눌렀는데, 새로고침된 페이지에 옛날 닉네임이 그대로 떠요!"*
- *"자유게시판에 글을 쓰고 '등록'을 눌렀는데 방금 쓴 글이 목록에 안 보여서, 글이 안 써진 줄 알고 똑같은 글을 3번 연속으로 올렸어요!"*
- *"주문 결제를 완료했는데 주문 완료 목록에 '주문 내역이 없습니다'라고 나와서 결제가 안 된 줄 알고 재결제했습니다!"*

더 기괴한 것은, 사용자가 당황해서 1~2초 뒤에 **F5(새로고침)를 한 번 더 누르면 방금 쓴 데이터가 마법처럼 정상적으로 나타난다**는 사실이었습니다!

*"Master DB에 데이터가 성공적으로 커밋된 다음에 리다이렉트시켰는데, 왜 조회 화면에선 방금 쓴 데이터가 안 보이다가 1초 뒤에야 나타나는 거죠?!"* 😱

---

### 왜 이런 참사가 발생했을까? (비동기 복제와 Replication Lag)

데이터베이스의 Master-Slave 복제는 쓰기 성능 저하를 막기 위해 대부분 **비동기 복제(Asynchronous Replication)** 방식으로 동작합니다:

```
[비동기 복제 아키텍처와 시차 발생 원리]

클라이언트                    Master DB                        Replica DB
   │                             │                                 │
   │ 1. WRITE (게시글 등록)       │                                 │
   ├────────────────────────────>│                                 │
   │                             │ 2. 트랜잭션 커밋 및 Binlog 기록   │
   │ 3. 200 OK (등록 성공 응답)   │                                 │
   │<────────────────────────────┤                                 │
   │                             │ 4. Binlog 네트워크 비동기 전송   │
   │                             ├────────────────────────────────>│ (Relay log 기록)
   │ 5. READ (방금 쓴 글 조회)    │                                 │
   ├─────────────────────────────┼────────────────────────────────>│ ⚠️ 아직 재생 안 됨!
   │                             │                                 │ (Replication Lag)
   │ 6. 404 Not Found (글 없음!) │                                 │
   │<────────────────────────────┼─────────────────────────────────┤
   │                             │                                 │ 7. SQL 스레드가 재생 완료!
```

1. 클라이언트가 Master DB에 데이터를 쓰고 커밋(`Commit`)을 완료합니다.
2. Master DB는 즉시 클라이언트에게 성공 응답을 반환합니다.
3. 동시에 Master는 변경 내역인 **바이너리 로그(Binary Log / Binlog)**를 네트워크를 통해 Replica로 전송합니다.
4. Replica의 I/O 스레드가 이를 받아 릴레이 로그(Relay Log)에 쓰고, **SQL 워커 스레드가 이벤트를 순차적으로 재생(Replay)**하여 자신의 스토리지에 반영합니다.
5. 이 네트워크 전송, 디스크 I/O, 슬레이브의 롱 쿼리 경합 등으로 인해 **수십 ms에서 수 초에 달하는 복제 지연(Replication Lag)**이 발생합니다!
6. 클라이언트가 쓰기 성공 직후 목록 페이지로 리다이렉트되어 Replica로 `SELECT`를 날리면, **아직 슬레이브에 트랜잭션이 반영되지 않아 방금 쓴 데이터가 보이지 않는 Stale Read 참사**가 발생합니다.

---

### Read-Your-Own-Writes (Write-After-Read) 일관성이란?

분산 시스템과 데이터베이스 이론(Martin Kleppmann의 *DDIA* 5장)에서 정의하는 핵심 일관성 모델입니다:

> **Read-Your-Own-Writes Consistency**:  
> 사용자가 직접 수정한 데이터는, **그 수정을 가한 사용자 본인이 조회할 때는 항상 최신 상태(자신의 변경 사항이 반영된 상태)로 보여야 한다**는 보장.

- **타인(Other Users)의 관점**:
  - 다른 사용자가 작성한 글이나 프로필은 몇 백 ms 정도 늦게 보여도 서비스 이용에 큰 지장이 없습니다 (최종 일관성 / Eventual Consistency 허용).
- **작성자 본인(Author)의 관점**:
  - 자신이 방금 입력하고 저장한 데이터가 즉시 보이지 않으면 시스템이 고장 났다고 인지하여 중복 요청을 유발하고 결제 사고로 이어집니다 (강한 일관성 / Strong Consistency 필수).

---

## 과제

당신은 데이터베이스의 복제 지연 환경에서 일관성 있는 읽기를 보장하는 **"Read-Your-Own-Writes 라우팅 시뮬레이터"**를 구현해야 합니다.

주어진 복제본 목록, 라우팅 정책, 그리고 시간순 데이터베이스 이벤트(쓰기, 슬레이브 복제 진행, 읽기)를 처리하고 각 읽기 요청의 라우팅 대상(Master vs Replica)과 일관성 위반 여부를 판정하십시오.

---

### 라우팅 정책 3종 스펙

1. **`NAIVE_REPLICA_ONLY` (나이브한 복제본 라우팅)**:
   - 모든 읽기 쿼리를 무조건 지정된 `target_replica_id`로 전송합니다.
   - 대상 슬레이브의 현재 적용된 GTID(`applied_gtid`)가 본인이 방금 작성한 트랜잭션의 GTID보다 뒤처져 있으면 `STALE_READ_ANOMALY` 에러를 발생시킵니다.
2. **`SESSION_MASTER_PINNING` (세션 기반 마스터 핀닝 윈도우)**:
   - 사용자가 마지막으로 쓰기를 수행한 시각으로부터 경과 시간($\Delta t = t - t_{\text{last\_write}}$)을 확인합니다.
   - 자신이 작성한 레코드를 조회할 때, $\Delta t < \text{master\_pinning\_window\_sec}$이면 강제로 **Master DB로 라우팅**하여 최신성을 보장합니다 (`ROUTED_TO_MASTER_PINNED`).
   - 핀닝 시간이 만료되었거나($\Delta t \ge \text{window}$), 자신이 작성하지 않은 레코드인 경우 슬레이브(`target_replica_id`)로 라우팅합니다.
3. **`CAUSAL_GTID_CONSISTENCY` (GTID 인과적 일관성 대기 및 적응형 폴백)**:
   - 본인이 작성한 레코드를 조회할 때:
     - 대상 슬레이브의 현재 GTID가 요구 GTID 이상이면 슬레이브에서 즉시 읽습니다 (대기 시간 0.0초).
     - 슬레이브의 현재 GTID가 뒤처져 있다면, 최대 `gtid_wait_timeout_sec` 동안 슬레이브가 해당 GTID까지 따라잡기를 기다립니다:
       - 제한 시간 내에 따라잡으면 **슬레이브에서 읽기 수행** (`wait_time_sec = 도달 시각 - 요청 시각`).
       - 제한 시간을 초과해도 못 따라잡으면 **Master DB로 폴백(Fallback)**하여 최신 데이터를 읽습니다 (`wait_time_sec = gtid_wait_timeout_sec`).
   - 본인이 작성하지 않은 레코드는 슬레이브에서 즉시 읽습니다.

---

### 입력 형식 (JSON)

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "routing_policy": "SESSION_MASTER_PINNING",
  "config": {
    "master_pinning_window_sec": 2.0,
    "gtid_wait_timeout_sec": 0.5
  },
  "replicas": [
    { "replica_id": "replica-1", "initial_applied_gtid": 100 },
    { "replica_id": "replica-2", "initial_applied_gtid": 95 }
  ],
  "timeline": [
    {
      "time": 10.0,
      "type": "WRITE",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "gtid_generated": 101
    },
    {
      "time": 10.2,
      "type": "REPLICATION_PROGRESS",
      "replica_id": "replica-1",
      "applied_gtid": 101
    },
    {
      "time": 10.3,
      "type": "READ",
      "request_id": "req-01",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-2"
    }
  ]
}
```

- `routing_policy`: `"NAIVE_REPLICA_ONLY"` | `"SESSION_MASTER_PINNING"` | `"CAUSAL_GTID_CONSISTENCY"`
- `config`:
  - `master_pinning_window_sec`: 마스터 핀닝 지속 시간(초, 실수 $\ge 0.0$)
  - `gtid_wait_timeout_sec`: 슬레이브 GTID 대기 타임아웃(초, 실수 $\ge 0.0$)
- `replicas`: 슬레이브 목록 및 시작 시점의 적용 완료 GTID
- `timeline`: 타임라인 이벤트 목록
  - `WRITE`: 쓰기 트랜잭션 커밋 (`time`, `user_id`, `table`, `record_id`, `gtid_generated`)
  - `REPLICATION_PROGRESS`: 슬레이브가 특정 GTID까지 복제 완료 (`time`, `replica_id`, `applied_gtid`)
  - `READ`: 읽기 쿼리 발생 (`time`, `request_id`, `user_id`, `table`, `record_id`, `target_replica_id`)

---

### 출력 형식 (JSON)

표준 출력(stdout)으로 다음 구조의 JSON 객체를 출력합니다 (인덴트 2칸):

```json
{
  "summary": {
    "routing_policy": "SESSION_MASTER_PINNING",
    "total_reads": 2,
    "reads_routed_to_master": 2,
    "reads_routed_to_replica": 0,
    "stale_read_anomalies": 0,
    "fresh_reads": 2,
    "master_read_ratio_pct": 100.0
  },
  "read_results": [
    {
      "request_id": "req-01",
      "time": 10.3,
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-2",
      "routed_to": "MASTER",
      "status": "SUCCESS_FRESH",
      "reason": "User pinned to Master within 2.0s window (elapsed: 0.3s)",
      "anomaly": null,
      "wait_time_sec": 0.0
    }
  ]
}
```

- `summary` 통계 필드:
  - `routing_policy`: 적용된 정책 이름
  - `total_reads`: 총 읽기 요청 수
  - `reads_routed_to_master`: 마스터로 라우팅된 읽기 수
  - `reads_routed_to_replica`: 복제본으로 라우팅된 읽기 수
  - `stale_read_anomalies`: `status == "STALE_READ_ANOMALY"` 발생 건수
  - `fresh_reads`: `status == "SUCCESS_FRESH"` 건수
  - `master_read_ratio_pct`: 전체 읽기 중 마스터로 간 비율(%, 소수점 둘째 자리 반올림)

---

## 입출력 예시

### 예시 1

#### 입력
```json
{
  "routing_policy": "NAIVE_REPLICA_ONLY",
  "config": {
    "master_pinning_window_sec": 2.0,
    "gtid_wait_timeout_sec": 0.5
  },
  "replicas": [
    { "replica_id": "replica-1", "initial_applied_gtid": 100 },
    { "replica_id": "replica-2", "initial_applied_gtid": 95 }
  ],
  "timeline": [
    {
      "time": 10.0,
      "type": "WRITE",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "gtid_generated": 101
    },
    {
      "time": 10.2,
      "type": "REPLICATION_PROGRESS",
      "replica_id": "replica-1",
      "applied_gtid": 101
    },
    {
      "time": 10.3,
      "type": "READ",
      "request_id": "req-01",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-2"
    },
    {
      "time": 10.4,
      "type": "READ",
      "request_id": "req-02",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-1"
    }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "routing_policy": "NAIVE_REPLICA_ONLY",
    "total_reads": 2,
    "reads_routed_to_master": 0,
    "reads_routed_to_replica": 2,
    "stale_read_anomalies": 1,
    "fresh_reads": 1,
    "master_read_ratio_pct": 0.0
  },
  "read_results": [
    {
      "request_id": "req-01",
      "time": 10.3,
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-2",
      "routed_to": "REPLICA",
      "status": "STALE_READ_ANOMALY",
      "reason": "Replica replica-2 at GTID 95 behind user write GTID 101",
      "anomaly": "ERR_READ_YOUR_OWN_WRITES_VIOLATION",
      "wait_time_sec": 0.0
    },
    {
      "request_id": "req-02",
      "time": 10.4,
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-1",
      "routed_to": "REPLICA",
      "status": "SUCCESS_FRESH",
      "reason": "Replica read completed",
      "anomaly": null,
      "wait_time_sec": 0.0
    }
  ]
}
```

---

### 예시 2

#### 입력
```json
{
  "routing_policy": "SESSION_MASTER_PINNING",
  "config": {
    "master_pinning_window_sec": 2.0,
    "gtid_wait_timeout_sec": 0.5
  },
  "replicas": [
    { "replica_id": "replica-1", "initial_applied_gtid": 100 },
    { "replica_id": "replica-2", "initial_applied_gtid": 95 }
  ],
  "timeline": [
    {
      "time": 10.0,
      "type": "WRITE",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "gtid_generated": 101
    },
    {
      "time": 10.2,
      "type": "REPLICATION_PROGRESS",
      "replica_id": "replica-1",
      "applied_gtid": 101
    },
    {
      "time": 10.3,
      "type": "READ",
      "request_id": "req-01",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-2"
    },
    {
      "time": 10.4,
      "type": "READ",
      "request_id": "req-02",
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-1"
    }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "routing_policy": "SESSION_MASTER_PINNING",
    "total_reads": 2,
    "reads_routed_to_master": 2,
    "reads_routed_to_replica": 0,
    "stale_read_anomalies": 0,
    "fresh_reads": 2,
    "master_read_ratio_pct": 100.0
  },
  "read_results": [
    {
      "request_id": "req-01",
      "time": 10.3,
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-2",
      "routed_to": "MASTER",
      "status": "SUCCESS_FRESH",
      "reason": "User pinned to Master within 2.0s window (elapsed: 0.3s)",
      "anomaly": null,
      "wait_time_sec": 0.0
    },
    {
      "request_id": "req-02",
      "time": 10.4,
      "user_id": "user_42",
      "table": "posts",
      "record_id": "post_999",
      "target_replica_id": "replica-1",
      "routed_to": "MASTER",
      "status": "SUCCESS_FRESH",
      "reason": "User pinned to Master within 2.0s window (elapsed: 0.4s)",
      "anomaly": null,
      "wait_time_sec": 0.0
    }
  ]
}
```
