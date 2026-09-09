# 문제 232: 분산 합의(Raft): 비대칭 네트워크 단절(Asymmetric Network Partition)과 디스럽티브 서버(Disruptive Server) 방어: Pre-Vote 프로토콜 vs CheckQuorum

## 1. 개요 및 배경 (Incident Scenario)

대규모 분산 키-값 저장소(etcd, CockroachDB, TiKV) 클러스터에서 비대칭 네트워크 단절(Asymmetric Network Partition / Partial Partition)이 발생하며 리더 노드가 무한정 강등(Demote)되고 쓰기 서비스가 전면 마비되는 장애(`DISRUPTIVE_SERVER_LEADER_ELECTION_STORM`)가 보고되었습니다.

클러스터는 총 5개 노드($L, A, B, C, D$, 쿼럼 Quorum = 3)로 구성되어 있으며, 노드 $L$이 정상 리더로 선출되어 클라이언트 쓰기 트래픽을 처리하고 있었습니다. 그러나 물리 스위치 포트 장애 및 방화벽 비대칭 드롭으로 인해 다음과 같은 이상 토폴로지가 형성되었습니다:

```
[비대칭 네트워크 단절(Asymmetric Partition) 토폴로지]
       +-----------------------+
       |   Leader (L, Term 1)  |
       +-------+-------+-------+
               |       |       | (Heartbeat OK)
               v       v       v
            +-----+ +-----+ +-----+
            |  A  | |  B  | |  C  |
            +--+--+ +--+--+ +--+--+
               ^       ^       ^
               |       |       | (Bidirectional Communication OK)
       +-------+-------+-------+
       | Isolated Follower (D) |  <--- L의 하트비트 수신 불가 (L -> D 패킷 유실)
       +-----------------------+       그러나 A, B, C와는 양방향 통신 정상!
```

### 왜 표준 Raft 알고리즘에서 장애가 발생하는가?
1. **D의 타임아웃과 텀(Term) 증가**:
   - 노드 $D$는 리더 $L$로부터 하트비트를 받지 못하므로 `election_timeout_ms`가 경과하면 스스로 Candidate로 승격합니다.
   - Raft 표준 규칙에 따라 $D$는 자신의 텀을 1 증가시켜 `Term = 2`로 만들고, 동료 노드($A, B, C$)에 `RequestVote(Term=2)` RPC를 브로드캐스트합니다.
2. **동료 노드들의 리더 강등 (Disruptive Server Storm)**:
   - 동료 노드 $A, B, C$는 리더 $L$과 정상적으로 통신 중이었음에도 불구하고, 수신된 RPC의 `Term=2`가 현재 클러스터 텀(`Term=1`)보다 크다는 표준 Raft 불변식(`If Term > currentTerm, set currentTerm = Term and convert to Follower`)에 의해 즉시 Follower 상태로 강등되고 텀을 2로 갱신합니다.
   - 리더 $L$ 역시 높은 텀 번호를 전달받고 리더 지위를 상실합니다.
3. **선출 실패와 무한 반복 (Leaderless Flapping)**:
   - 그러나 $D$는 최신 로그를 가지고 있지 않거나 쿼럼을 확보하지 못해 리더로 당선되지 못합니다.
   - 이후 노드 $A$ 등이 새 리더(Term 3)로 선출되지만, $D$는 여전히 리더의 하트비트를 받지 못하므로 다시 타임아웃 후 `Term=4`로 `RequestVote`를 보내 클러스터를 다시 붕괴시킵니다.
   - 이로 인해 클러스터는 리더 선출 폭풍에 휩싸여 쓰기 가용성이 0%로 추락합니다.

### 해결책: Pre-Vote 프로토콜 (Diego Ongaro §9.6) & CheckQuorum
- **Pre-Vote 프로토콜**:
  - 노드는 정식 텀을 올리기 전에 가상 텀(`Term + 1`)으로 동료 노드들에게 **사전 투표(`PreVote`)**를 요청합니다.
  - 투표 노드($A, B, C$)는 후보자의 로그 최신성뿐만 아니라 **"자신이 최근 리더로부터 유효한 하트비트를 받았는가(Leader Lease 유효 여부)"**를 검사합니다.
  - $A, B, C$는 리더 $L$로부터 정상 하트비트를 받고 있으므로 $D$의 PreVote 요청을 일제히 거절합니다.
  - 따라서 $D$는 텀을 올리지 못하고 정식 선거를 시작할 수 없으므로 리더 $L$은 전혀 방해받지 않고 안정적으로 유지됩니다(`OPTIMAL_PREVOTE_CHECK_QUORUM_DEFENSE`).
- **CheckQuorum**:
  - 리더가 과반수 노드로부터 하트비트 응답을 받지 못하고 고립된 대칭 단절 상황에서는 스스로 리더 지위를 내려놓아 스플릿 브레인을 방지합니다(`LEADER_ISOLATED_VOLUNTARY_STEPDOWN`).

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "prevote_enabled": true,
    "check_quorum_enabled": true,
    "election_timeout_ms": 1000,
    "heartbeat_interval_ms": 200
  },
  "topology": {
    "nodes": ["L", "A", "B", "C", "D"],
    "initial_leader": "L",
    "partition_type": "ASYMMETRIC"
  },
  "workload": {
    "simulation_rounds": 5,
    "client_write_requests": 1000
  }
}
```

### 필드 설명
- `config`:
  - `prevote_enabled` (bool): Raft Pre-Vote 프로토콜 활성화 여부
  - `check_quorum_enabled` (bool): 리더의 쿼럼 검증 및 자진 강등 메커니즘 활성화 여부
  - `election_timeout_ms` (int): 선거 타임아웃 (ms)
  - `heartbeat_interval_ms` (int): 리더 하트비트 주기 (ms)
- `topology`:
  - `nodes` (list[str]): 클러스터 노드 식별자 목록
  - `initial_leader` (str): 초기 리더 노드 ID
  - `partition_type` (str):
    - `"HEALTHY"`: 모든 노드 정상 연결
    - `"ASYMMETRIC"`: 노드 D가 리더 L의 하트비트를 수신할 수 없으나 A, B, C와는 양방향 통신 가능
    - `"SYMMETRIC_LEADER_ISOLATION"`: 리더 L이 모든 팔로워 노드(A, B, C, D)로부터 완전 고립
- `workload`:
  - `simulation_rounds` (int): 시뮬레이션 라운드 수 (선거 타임아웃 틱 수)
  - `client_write_requests` (int): 클러스터에 인입된 클라이언트 쓰기 요청 수

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_PREVOTE_CHECK_QUORUM_DEFENSE",
  "metrics": {
    "leader": "L",
    "leader_term": 1,
    "leader_demotions": 0,
    "disruptive_elections": 0,
    "write_success_rate": 1.0,
    "split_brain_detected": false
  }
}
```

### 판정(Verdict) 및 상태(Status) 규칙
1. **`partition_type == "HEALTHY"`**:
   - `status`: `"SUCCESS"`
   - `verdict`: `"RAFT_CLUSTER_HEALTHY_STABLE"`
   - `write_success_rate`: `1.0`, `split_brain_detected`: `false`
2. **`partition_type == "SYMMETRIC_LEADER_ISOLATION"`**:
   - `check_quorum_enabled == false`:
     - 고립된 구 리더가 자신을 리더로 착각하여 쓰기 요청 처리 시도 -> 스플릿 브레인 발생
     - `status`: `"FAILED"`, `verdict`: `"SPLIT_BRAIN_STALE_LEADER_WRITE_ATTEMPT"`
     - `split_brain_detected`: `true`, `write_success_rate`: `0.0`
   - `check_quorum_enabled == true`:
     - 리더 L이 쿼럼 상실을 감지하고 자진 강등, 과반수 그룹(A, B, C, D)이 새 리더(A)를 Term 2로 선출
     - `status`: `"SUCCESS"`, `verdict`: `"LEADER_ISOLATED_VOLUNTARY_STEPDOWN"`
     - `leader`: `"A"`, `leader_term`: `2`, `leader_demotions`: `1`, `write_success_rate`: `1.0`
3. **`partition_type == "ASYMMETRIC"`**:
   - `prevote_enabled == false`:
     - 고립 노드 D가 텀을 올려 RequestVote를 브로드캐스트하여 매 라운드 리더 강등 발생
     - `status`: `"FAILED"`, `verdict`: `"DISRUPTIVE_SERVER_LEADER_ELECTION_STORM"`
     - 라운드마다 리더 강등 및 텀 증가, 쓰기 요청 손실 발생 (`failed_writes += int(client_write_requests / simulation_rounds)`)
   - `prevote_enabled == true`:
     - 동료 노드들이 리더 리스 유효성을 근거로 D의 PreVote를 거절, D의 텀 증가 차단
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_PREVOTE_CHECK_QUORUM_DEFENSE"`
     - `leader`: `"L"`, `leader_term`: `1`, `leader_demotions`: `0`, `disruptive_elections`: `0`, `write_success_rate`: `1.0`

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "prevote_enabled": false,
    "check_quorum_enabled": true,
    "election_timeout_ms": 1000,
    "heartbeat_interval_ms": 200
  },
  "topology": {
    "nodes": ["L", "A", "B", "C", "D"],
    "initial_leader": "L",
    "partition_type": "ASYMMETRIC"
  },
  "workload": {
    "simulation_rounds": 5,
    "client_write_requests": 1000
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "FAILED",
  "verdict": "DISRUPTIVE_SERVER_LEADER_ELECTION_STORM",
  "metrics": {
    "leader": "A",
    "leader_term": 11,
    "leader_demotions": 5,
    "disruptive_elections": 5,
    "write_success_rate": 0.0,
    "split_brain_detected": false
  }
}
```
