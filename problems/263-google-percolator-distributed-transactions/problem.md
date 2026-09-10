# [분산 트랜잭션/NewSQL] Google Percolator 2-Phase MVCC 분산 트랜잭션: Primary/Secondary Lock, 충돌 해소 및 크래시 롤포워드(Roll-Forward) 복구 엔진

## 문제 설명

구글의 웹 검색 인덱스 갱신 파이프라인(Google Caffeine)을 위해 2010년 USENIX OSDI에서 발표된 **Google Percolator**는 기존의 전통적인 2단계 커밋(2PC, Two-Phase Commit)의 코디네이터 단일 장애점(SPOF)과 블로킹 한계를 극복한 전설적인 **스냅샷 격리(Snapshot Isolation) 분산 트랜잭션 프로토콜**입니다.

오늘날 PingCAP TiDB / TiKV, CockroachDB, YugabyteDB 등 글로벌 NewSQL 및 분산 관계형 데이터베이스의 분산 트랜잭션 엔진은 모두 이 Percolator 알고리즘을 기반으로 구현되어 있습니다.
Percolator는 Bigtable이나 RocksDB와 같은 단순한 분산 분산 Key-Value 저장소 위에 세 개의 컬럼 패밀리(**`data`**, **`lock`**, **`write`**)를 구축하고, 중앙 집중식 트랜잭션 매니저 없이 **기본 키(Primary Key)와 보조 키(Secondary Key)** 간의 비대칭적 불변식(Invariant)만을 이용하여 ACID 트랜잭션을 완성합니다.

특히 가장 우아한 설계는 **분산 노드 및 코디네이터 크래시 복구 메커니즘**입니다:
트랜잭션 코디네이터가 Prewrite를 마치고 Commit 단계에서 Primary Key만 커밋한 채 서버가 폭발하거나 네트워크가 단절되어 사망하더라도, 나중에 해당 Secondary Key에 접근하는 다른 트랜잭션이나 리더(Reader)가 만료된 락을 발견하고 Primary Key의 상태를 조회하여 **스스로 트랜잭션을 끝까지 완결시키는 롤포워드(Roll-Forward)**를 수행합니다!
반대로 Primary Key가 커밋되기 전에 코디네이터가 사망했다면, 잔류 락을 즉시 지우고 롤백 마커를 남겨 죽은 트랜잭션이 영원히 부활하지 못하도록 봉인(Roll-Back)합니다.

NewSQL 스토리지 엔진 아키텍트가 되어, 타임스탬프 기반 MVCC 스냅샷 읽기, 2단계 사전쓰기(Prewrite) 충돌 검사, Primary 락 커밋의 불가역성 보장, 그리고 분산 크래시 상황에서의 자가 치유 롤포워드/롤백 복구를 완벽히 구현하는 **Google Percolator 분산 트랜잭션 엔진**을 구축하십시오.

---

## Percolator 스토리지 및 트랜잭션 프로토콜 규격

### 1. 3대 컬럼 패밀리 (Column Families)
- **`data`**: 트랜잭션 시작 시점($T_{\text{start}}$)에 기록된 실제 값: `data:(key, start_ts) = value`.
- **`lock`**: 현재 진행 중인 트랜잭션의 락 정보: `lock:key = {primary_key, start_ts, ttl, op}`.
  - 모든 Secondary Key의 락은 Primary Key의 위치를 가리킵니다.
- **`write`**: 트랜잭션이 성공적으로 커밋된 시점($T_{\text{commit}}$)의 메타데이터: `write:(key, commit_ts) = {start_ts, write_type}`.
  - `write_type`: `"PUT"`, `"DELETE"`, 또는 롤백 마커인 `"ROLLBACK"`.

### 2. 스냅샷 읽기 (Snapshot Read at $T_{\text{read}}$)
1. 읽으려는 키에 락(`lock:key`)이 존재하는지 검사:
   - 락의 시작 시점이 $T_{\text{lock}} \le T_{\text{read}}$인 경우:
     - 락이 아직 유효한 경우 (`current_time < lock.start_ts + lock.ttl`):
       - 트랜잭션이 아직 실행 중이므로 읽기가 차단됩니다 (`"BLOCKED_BY_LOCK"`).
     - 락이 만료된 경우 (`current_time >= lock.start_ts + lock.ttl`):
       - 잔류 락을 해소(Resolve Lock)한 후 읽기를 재개합니다.
2. 락이 없거나 해소된 후:
   - `write` 컬럼 패밀리에서 $T_{\text{commit}} \le T_{\text{read}}$이면서 `write_type != "ROLLBACK"`인 최신 레코드를 탐색.
   - 레코드가 없으면 `"NOT_FOUND"`.
   - 최신 레코드의 `write_type == "DELETE"`이면 `"DELETED"`.
   - 최신 레코드의 `write_type == "PUT"`이면 `data:(key, record.start_ts)`의 값을 읽어 반환 (`"OK"`).

### 3. 2단계 사전쓰기 (Two-Phase Prewrite at $T_{\text{start}}$)
- 트랜잭션이 수정할 키 목록 중 첫 번째 키를 **Primary Key**로 선정하고, 나머지를 **Secondary Keys**로 분류합니다.
- Primary Key부터 시작하여 Secondary Keys 순으로 다음 검사를 수행:
  1. **쓰기-쓰기 충돌(Write-Write Conflict) 검사**:
     - 해당 키에 대해 $T_{\text{commit}} \ge T_{\text{start}}$인 커밋 레코드(ROLLBACK 제외)가 이미 존재하는가?
     - 존재한다면 다른 트랜잭션이 먼저 커밋한 것이므로 즉시 `"WRITE_CONFLICT"` 에러와 함께 중단.
  2. **락 충돌(Lock Conflict) 검사**:
     - 해당 키에 임의의 트랜잭션의 활성 락이 이미 존재하는가?
     - 존재한다면 즉시 `"LOCK_CONFLICT"` 에러와 함께 중단.
  3. 충돌이 없으면 `data:(key, start_ts)`에 값을 기록하고, `lock:key`에 Primary 키를 참조하는 락을 기록.
- 도중에 충돌이 발생하면, 현재 트랜잭션이 이미 기록한 모든 락과 데이터를 즉시 정리(Clean-up)합니다.

### 4. 커밋 단계 (Commit Phase at $T_{\text{commit}}$)
1. **Primary Key 커밋**:
   - `lock:primary_key`가 존재하는지, 그리고 해당 락의 `start_ts`가 일치하는지 확인.
   - Primary 락이 없거나 이미 롤백 마커가 기록되어 있다면 트랜잭션 실패 (`"PRIMARY_LOCK_NOT_FOUND"` 또는 `"ALREADY_ROLLED_BACK"`).
   - `write:(primary_key, commit_ts)`에 커밋 메타데이터를 기록하고 `lock:primary_key`를 삭제.
   - **불가역성의 순간(The Point of No Return)**: Primary Key의 커밋 레코드가 기록되는 순간, **이 트랜잭션은 법적으로 완전히 커밋된 것**으로 확정됩니다!
2. **Secondary Keys 커밋 (비동기 처리 가능)**:
   - 각 보조 키에 대해 `write:(secondary_key, commit_ts)`를 기록하고 `lock:secondary_key`를 삭제.

### 5. 크래시 복구 및 락 해소 (Crash Recovery / Resolve Lock)
- 만료된 락(`lock:key`)을 만난 제3의 프로세스는 락에 명시된 `primary_key`의 상태를 검사합니다:
  - **Case 1: Primary Key가 이미 커밋되어 있는 경우**:
    - 트랜잭션이 커밋된 상태에서 코디네이터가 사망한 것임!
    - **롤포워드(Roll-Forward)**: 해당 Secondary Key에 대해 Primary Key와 동일한 $T_{\text{commit}}$으로 `write` 레코드를 기록하고 락을 삭제 (`"ROLLED_FORWARD"`).
  - **Case 2: Primary Key의 커밋 레코드가 없는 경우**:
    - 트랜잭션이 커밋되기 전에 코디네이터가 사망한 것임!
    - **롤백(Roll-Back)**: 잔류 락을 삭제하고, 해당 $T_{\text{start}}$의 임시 `data`를 삭제하며, 향후 좀비 프로세스가 뒤늦게 Primary를 커밋하지 못하도록 `write:(primary_key, start_ts) = {start_ts, write_type: "ROLLBACK"}` 마커를 기록 (`"ROLLED_BACK"`).

---

## 입력 형식

표준 입력(`sys.stdin`)으로 초기 스토리지 상태와 일련의 트랜잭션 명령 목록이 포함된 JSON이 주어집니다:
```json
{
  "initial_state": {
    "data": [{"key": "acc:Alice", "start_ts": 1, "value": "1000"}],
    "writes": [{"key": "acc:Alice", "commit_ts": 2, "start_ts": 1, "write_type": "PUT"}]
  },
  "operations": [
    {
      "id": "OP_01",
      "type": "PREWRITE",
      "primary_key": "acc:Alice",
      "start_ts": 10,
      "ttl": 50,
      "mutations": [
        {"key": "acc:Alice", "value": "900", "op": "PUT"},
        {"key": "acc:Bob", "value": "600", "op": "PUT"}
      ]
    },
    {
      "id": "OP_02",
      "type": "COMMIT",
      "primary_key": "acc:Alice",
      "start_ts": 10,
      "commit_ts": 15,
      "keys": ["acc:Alice", "acc:Bob"]
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 작업별 실행 결과, 통계 요약 메트릭, 최종 스토리지 상태가 포함된 단일 라인 JSON을 출력합니다:
```json
{
  "stats": {
    "prewrite_success": 1,
    "prewrite_conflicts": 0,
    "commit_success": 1,
    "commit_crashed": 0,
    "reads_successful": 0,
    "reads_blocked": 0,
    "roll_forwards": 0,
    "roll_backs": 0
  },
  "operation_results": [
    {
      "id": "OP_01",
      "type": "PREWRITE",
      "status": "OK",
      "primary_key": "acc:Alice",
      "prewritten_count": 2,
      "start_ts": 10
    },
    {
      "id": "OP_02",
      "type": "COMMIT",
      "status": "COMMITTED",
      "primary_key": "acc:Alice",
      "commit_ts": 15,
      "committed_keys_count": 2
    }
  ],
  "final_state": {
    "active_locks_count": 0,
    "committed_versions_count": 3,
    "rollback_records_count": 0,
    "active_locks": [],
    "latest_writes": [
      {"key": "acc:Alice", "commit_ts": 2, "start_ts": 1, "write_type": "PUT"},
      {"key": "acc:Alice", "commit_ts": 15, "start_ts": 10, "write_type": "PUT"},
      {"key": "acc:Bob", "commit_ts": 15, "start_ts": 10, "write_type": "PUT"}
    ]
  }
}
```
