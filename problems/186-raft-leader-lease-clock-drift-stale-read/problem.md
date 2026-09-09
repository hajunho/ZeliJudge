# Problem 186: Raft 리더 리스(Leader Lease) 클록 드리프트(Clock Drift), GC 일시정지와 오래된 읽기(Stale Read) 선형성 파괴 방어

## 문제 설명

글로벌 분산 트랜잭션 데이터베이스 및 분산 키-값 저장소(CockroachDB, TiKV, etcd, Consul 등)를 운영하는 인프라 아키텍처 팀은 Raft 합의 클러스터의 읽기 처리량(Read Throughput)을 극대화하기 위해 **리더 리스(Leader Lease)** 기법을 도입했습니다.

기본 Raft 프로토콜에서 선형성 읽기(Linearizable Read)를 수행하려면, 리더는 자신이 여전히 합법적인 리더인지 확인하기 위해 매 읽기 요청마다 과반수 노드에게 하트비트 라운드트립(**`ReadIndex` 쿼럼 통신**)을 거쳐야 합니다. 이로 인해 읽기 지연시간에 최소 $15\sim25\,\text{ms}$의 네트워크 RTT가 추가되었습니다.

이를 해결하기 위해 팔로워들이 일정 시간(예: $500\,\text{ms}$) 동안 새 리더 선출을 시도하지 않겠다고 약속하는 **리더 리스(Leader Lease)**를 부여하면, 리더는 네트워크 통신 없이 로컬 메모리 캐시에서 $0.5\,\text{ms}$ 초저지연으로 즉시 읽기를 반환할 수 있습니다.

그러나 대규모 프로덕션 환경에서 다음과 같은 치명적인 **선형성 파괴(Linearizability Violation) 참사**가 관측되었습니다:
1. **클록 드리프트(Clock Drift)와 시간 지연 왜곡**: NTP 시계 동기화 오류, 가상화 하이퍼바이저 타임 슬라이스 왜곡 등으로 인해 리더 노드의 로컬 시계가 실제 벽시계(Wallclock) 시간보다 $150\,\text{ms}$ 뒤처지기 시작했습니다.
2. **팔로워의 리스 만료 및 신규 리더 선출**: 팔로워들의 관점에서는 리스 기간($500\,\text{ms}$)이 이미 종료되었으므로, 타임아웃 후 새로운 리더(Node 2, Term 2)를 선출하고 클라이언트로부터 새로운 쓰기(`balance = 5000`)를 승인 및 커밋했습니다.
3. **구 리더의 좀비 리스 착각과 오래된 읽기(Stale Read) 유출**: 시계가 느리게 가던 구 리더(Node 1)는 자신의 로컬 시계 기준으로 아직 리스가 유효하다고 착각하고, 클라이언트의 조회 요청에 대해 과거의 커밋 데이터(`balance = 1000`)를 버젓이 반환했습니다! 최신 잔액이 $5,000$으로 갱신되었음에도 과거 잔액 $1,000$이 노출되는 심각한 비일관성이 발생한 것입니다.

당신은 Raft의 3대 읽기 정책(나이브 월클록 리스, 엄격한 ReadIndex 쿼럼, 안전 바운디드 리스)을 정밀하게 시뮬레이션하고, 클록 오차 발생 시 선형성 무결성을 수호하는 합의 읽기 진단 엔진을 구축해야 합니다.

---

## 핵심 읽기 정책 (Read Policies)

### 1. `NAIVE_WALLCLOCK_LEASE` (나이브 월클록 리스 모드)
- 시스템의 월클록(`System.currentTimeMillis()`)을 그대로 신뢰하여 리스 만료 여부(`local_clock < lease.expiry`)를 판단합니다.
- 클록 드리프트로 인해 리더의 시계가 실제 시간보다 느려지면, 팔로워들에 의해 이미 폐위(Demote)되었음에도 자신이 여전히 리더라고 오판하여 로컬 캐시의 오래된 데이터를 반환합니다 (`STALE_LOCAL_LEASE_ANOMALY`).
- 평가 판정(Verdict): `STALE_READ_LINEARIZABILITY_VIOLATION` (오래된 읽기 1건 이상 발생 시 `status: FAILED`)

### 2. `STRICT_READ_INDEX_QUORUM` (엄격한 쿼럼 ReadIndex 모드)
- 로컬 시계를 전혀 신뢰하지 않습니다.
- 모든 단일 읽기 요청마다 과반수 팔로워 노드에게 하트비트를 전송하여 자신이 현재 텀(Term)의 리더임을 물리적으로 확인합니다.
- 지연시간은 항상 쿼럼 RTT($20\,\text{ms}$)와 로컬 조회 시간($0.5\,\text{ms}$)의 합($20.5\,\text{ms}$)이 소요되지만, **선형성 위반(Stale Read)이 0건으로 100% 방어**됩니다.
- 평가 판정(Verdict): `LINEARIZABLE_QUORUM_HEARTBEAT_OVERHEAD`

### 3. `SAFE_BOUNDED_LEASE` (안전 바운디드 리스 모드 - Spanner/TiKV 방식)
- 단조 증가 시계(`CLOCK_MONOTONIC_RAW`)와 최대 클록 불확실성 상한선($\epsilon$, `clock_drift_max_tolerance_ms`)을 안전 마진으로 도입합니다.
- 유효 안전 리스 지속 시간:
  $$\text{safe\_duration} = \text{lease\_duration} - 2\epsilon$$
- 리더 노드의 클록 드리프트가 허용 오차($\epsilon$)를 초과하거나, 로컬 시계가 안전 리스 만료 시각(`granted_at + safe_duration`)에 도달하면, **즉시 ReadIndex 쿼럼 하트비트로 자동 폴백(Fallback)**합니다.
- 정상 상황에서는 $0.5\,\text{ms}$ 초저지연 로컬 조회를 달성하고, 시계 이상이나 리더 교체 시에는 100% 안전하게 최신 데이터를 반환합니다.
- 평가 판정(Verdict): `OPTIMAL_SAFE_BOUNDED_LEASE`

---

## 이벤트 연산 명세

워크로드는 다음 5대 이벤트로 구성됩니다:
- `LEASE_RENEW`: 리더가 팔로워들로부터 리스를 갱신받음 (`wallclock_ms`, `leader_id`, `term`).
- `WRITE`: 클러스터에 데이터 쓰기 커밋 (`wallclock_ms`, `leader_id`, `term`, `key`, `value`).
- `SET_CLOCK_DRIFT`: 특정 노드의 시계 편차 설정 (`node_id`, `drift_ms`).
- `NEW_LEADER_ELECTED`: 새로운 텀의 신규 리더 선출 및 데이터 동기화 (`wallclock_ms`, `new_leader_id`, `term`).
- `READ`: 클라이언트의 키 조회 요청 (`wallclock_ms`, `node_id`, `key`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "read_policy": "SAFE_BOUNDED_LEASE",
    "lease_duration_ms": 500.0,
    "clock_drift_max_tolerance_ms": 50.0,
    "quorum_heartbeat_rtt_ms": 20.0,
    "local_read_latency_ms": 0.5
  },
  "workload": [
    {"op": "LEASE_RENEW", "wallclock_ms": 0.0, "leader_id": "node_1", "term": 1},
    {"op": "WRITE", "wallclock_ms": 100.0, "leader_id": "node_1", "term": 1, "key": "balance", "value": 1000},
    {"op": "READ", "wallclock_ms": 200.0, "node_id": "node_1", "key": "balance"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "read_policy": "SAFE_BOUNDED_LEASE",
    "total_reads": 1,
    "stale_reads": 0,
    "stale_read_rate": 0.0,
    "local_lease_reads": 1,
    "quorum_reads": 0,
    "lease_read_ratio": 1.0,
    "average_latency_ms": 0.5
  },
  "metrics": {
    "total_reads": 1,
    "stale_reads": 0,
    "stale_read_rate": 0.0,
    "local_lease_reads": 1,
    "quorum_reads": 0,
    "lease_read_ratio": 1.0,
    "average_latency_ms": 0.5,
    "verdict": "OPTIMAL_SAFE_BOUNDED_LEASE"
  },
  "sample_reads": [
    {
      "wallclock_ms": 200.0,
      "node_id": "node_1",
      "key": "balance",
      "read_value": 1000,
      "expected_true_value": 1000,
      "read_type": "SAFE_LOCAL_LEASE",
      "is_stale": false,
      "latency_ms": 0.5
    }
  ]
}
```

> **성공 기준**: `stale_reads == 0`일 때 `status: "SUCCESS"`, 1건이라도 오래된 값이 반환되면 선형성 위반으로 `status: "FAILED"`.
