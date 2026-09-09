# Problem 174: PostgreSQL SSI (Serializable Snapshot Isolation)과 쓰기 왜곡(Write Skew) 시뮬레이터

## 문제 설명

병원 야간 응급실 시스템에서 최소 1명 이상의 의사가 당직 근무를 서야 한다는 비즈니스 불변식이 존재함에도 불구하고, `REPEATABLE READ` 격리 수준에서 두 명의 의사가 동시에 사직/퇴근을 신청하여 당직 의사가 0명이 되는 심각한 의료 사고(**쓰기 왜곡, Write Skew**)가 발생했습니다.

기존 MVCC는 서로 다른 행(Disjoint Rows)에 대한 동시 쓰기를 충돌로 감지하지 못하지만, PostgreSQL의 **Serializable Snapshot Isolation (SSI)**은 메모리 기반의 **`SIREAD` 락**과 **rw 반의존성(rw-antidependency) 방향 그래프**를 추적하여 직렬화 이상 사이클이 형성되는 순간 피벗 트랜잭션을 즉시 롤백시킵니다.

당신은 데이터베이스 트랜잭션 엔진 엔지니어로서, **REPEATABLE READ**와 **SSI** 격리 엔진을 정밀 시뮬레이션하여 쓰기 왜곡 발생 및 SSI의 SQLSTATE `40001` 방어 메커니즘을 검증해야 합니다.

---

## 시뮬레이터 시스템 명세 및 동작 규칙

### 1. 입력 명세
- `initial_database`: 초기 데이터베이스 키-값 맵 (예: `{"doctor_alice": true, "doctor_bob": true}`).
- `isolation_mode`: `"REPEATABLE_READ"` 또는 `"SSI"`.
- `operations`: 트랜잭션 연산 목록 (순차적 타임라인):
  - `{"op": "BEGIN", "tx_id": "tx_1"}`: 트랜잭션 시작.
  - `{"op": "READ", "tx_id": "tx_1", "key": "k"}`: 키 읽기 (SSI에서는 `SIREAD` 락 등록 및 rw 엣지 검사).
  - `{"op": "WRITE", "tx_id": "tx_1", "key": "k", "val": v}`: 키 쓰기 (언커밋 버퍼에 기록 및 rw 엣지 검사).
  - `{"op": "COMMIT", "tx_id": "tx_1"}`: 트랜잭션 커밋 시도.

### 2. rw 반의존성 (rw-antidependency) 규칙
- 트랜잭션 $T_1$과 $T_2$의 실행 시간(Lifespan)이 시간적으로 겹치는(Concurrent) 경우:
  - $T_1$이 키 $K$를 읽었고(SIREAD), $T_2$가 동일한 키 $K$를 수정(`write`)한 경우:
    $$T_1 \xrightarrow{rw} T_2$$
  - 이는 $T_1$이 $T_2$보다 시간상 먼저 실행된 것으로 직렬화되어야 함을 나타내는 방향성 반의존성 엣지입니다.

### 3. 격리 모드별 커밋 규칙
1. **`REPEATABLE_READ` 모드**:
   - 서로 다른 키를 수정한 트랜잭션들은 쓰기-쓰기 충돌이 없으므로 무조건 커밋을 승인합니다.
   - 쓰기 왜곡(Write Skew)이 발생하더라도 아무런 경고 없이 둘 다 커밋됩니다.
2. **`SSI` 모드**:
   - 커밋을 시도하는 트랜잭션 $T$에 대해, 이미 커밋된 트랜잭션들과의 연결 관계를 평가합니다:
     - $T$의 인입 엣지($\text{rw\_in}$)에 이미 `COMMITTED`된 트랜잭션이 존재하고,
     - 동시에 $T$의 진출 엣지($\text{rw\_out}$)에도 이미 `COMMITTED`된 트랜잭션이 존재하거나 상호 순환 사이클이 형성된 경우:
     - $T$는 직렬화 이상을 유발하는 피벗(Pivot) 트랜잭션으로 판정되어 **즉시 롤백(`ABORTED_SERIALIZATION_FAILURE`)**됩니다.
     - 에러 정보: `sqlstate = "40001"`, `reason = "could not serialize access due to read/write dependencies among transactions"`.
   - 사이클이 없다면 커밋을 승인하고 데이터베이스에 최종 반영합니다.

### 4. 최종 판정 (Verdict)
- **`SERIALIZATION_ANOMALY_PREVENTED_SSI`**: SSI 모드에서 쓰기 왜곡 또는 직렬화 이상 사이클을 감지하여 최소 1개 이상의 트랜잭션을 40001로 롤백 방어한 경우.
- **`CATASTROPHIC_WRITE_SKEW_OCCURRED`**: REPEATABLE_READ 모드에서 쓰기 왜곡이 발생하여 데이터 불변식이 깨진 경우.
- **`SERIALIZABLE_CONCURRENT_EXECUTION`**: 이상 현상 없이 모든 트랜잭션이 정상적으로 직렬화 가능하게 완료된 경우.

---

## 입출력 예시

### 입력 (JSON)
```json
{
  "initial_database": { "doctor_alice": true, "doctor_bob": true },
  "isolation_mode": "SSI",
  "operations": [
    { "op": "BEGIN", "tx_id": "tx_alice" },
    { "op": "BEGIN", "tx_id": "tx_bob" },
    { "op": "READ", "tx_id": "tx_alice", "key": "doctor_alice" },
    { "op": "READ", "tx_id": "tx_alice", "key": "doctor_bob" },
    { "op": "READ", "tx_id": "tx_bob", "key": "doctor_alice" },
    { "op": "READ", "tx_id": "tx_bob", "key": "doctor_bob" },
    { "op": "WRITE", "tx_id": "tx_alice", "key": "doctor_alice", "val": false },
    { "op": "WRITE", "tx_id": "tx_bob", "key": "doctor_bob", "val": false },
    { "op": "COMMIT", "tx_id": "tx_alice" },
    { "op": "COMMIT", "tx_id": "tx_bob" }
  ]
}
```

### 출력 (JSON)
```json
{
  "status": "SUCCESS",
  "isolation_mode": "SSI",
  "metrics": {
    "total_transactions": 2,
    "committed_transactions": 1,
    "aborted_transactions": 1,
    "total_siread_locks": 4,
    "total_rw_edges": 2,
    "verdict": "SERIALIZATION_ANOMALY_PREVENTED_SSI"
  },
  "final_database": {
    "doctor_alice": false,
    "doctor_bob": true
  },
  "transaction_results": {
    "tx_alice": { "status": "COMMITTED", "tx_id": "tx_alice", "mode": "SSI" },
    "tx_bob": {
      "status": "ABORTED_SERIALIZATION_FAILURE",
      "tx_id": "tx_bob",
      "sqlstate": "40001",
      "reason": "could not serialize access due to read/write dependencies among transactions",
      "mode": "SSI"
    }
  }
}
```
