# Problem 181: Raft 분산 합의 클러스터 멤버십 변경과 공동 합의(Joint Consensus, $C_{old,new}$) 스플릿 브레인 방어

## 문제 설명

대규모 분산 트랜잭션 데이터베이스(etcd / TiKV 기반)를 운영하는 인프라 엔지니어링 팀은 트래픽 폭증에 대비하여 기존 3노드 클러스터(`[1, 2, 3]`)를 5노드 클러스터(`[1, 2, 3, 4, 5]`)로 무중단 확장하는 작업을 진행했습니다.
그러나 설정 변경을 나이브하게 1단계로 단번에 브로드캐스트(`enable_joint_consensus == false`)하는 실수를 저지른 결과,
비대칭 네트워크 지연으로 인해 **일부 노드는 과거 설정($C_{old}$)을 유지하고 신규 노드들은 새 설정($C_{new}$)을 적용한 상태에서 독립적인 두 개의 과반수가 형성되어 2명의 리더가 동시에 선출되는 치명적인 스플릿 브레인(Split-Brain) 참사**가 발생했습니다.

서로 다른 두 리더가 독립적으로 클라이언트 트랜잭션을 커밋하면서 데이터베이스 스토리지의 로그가 영구적으로 분기되고 수억 원 규모의 결제 데이터 불일치가 터졌습니다.

당신은 Diego Ongaro 박사의 Raft 논문(Section 6)에 명시된 **공동 합의(Joint Consensus, $C_{old,new}$)**와 **이중 쿼럼(Dual-Majority)** 규칙을 구현하여, 클러스터 멤버십 변경 중에도 스플릿 브레인을 100% 원천 차단하는 안전한 분산 엔진을 구축해야 합니다.

---

## 핵심 처리 규칙

### 1. 설정 구조 및 이중 쿼럼(Dual-Majority) 검증

각 노드는 현재 활성 설정(`active_config`)을 가집니다:

#### 단일 설정 (`type: "SINGLE"`)
- `nodes` 리스트를 가지며, 과반수 조건은 다음과 같습니다:
  $$\text{needed} = \lfloor \frac{|nodes|}{2} \rfloor + 1$$
  $$\text{valid} \iff |acks \cap nodes| \ge needed$$

#### 공동 합의 설정 (`type: "JOINT"`)
- `old_nodes`와 `new_nodes` 두 개의 집합을 동시에 가집니다.
- **이중 쿼럼(Dual-Majority) 규칙**:
  $$\text{needed\_old} = \lfloor \frac{|old\_nodes|}{2} \rfloor + 1, \quad \text{needed\_new} = \lfloor \frac{|new\_nodes|}{2} \rfloor + 1$$
  $$\text{valid} \iff (|acks \cap old\_nodes| \ge needed\_old) \land (|acks \cap new\_nodes| \ge needed\_new)$$
  두 설정 집합 각각에서 동시에 과반수를 얻어야만 유효한 쿼럼으로 인정됩니다.

---

### 2. 이벤트 처리 파이프라인

#### A. `START_RECONFIG` (멤버십 변경 시작)
- `enable_joint_consensus == false` (나이브 모드):
  - `nodes_updated_to_cnew`에 명시된 노드들만 $C_{new}$ 단일 설정으로 갱신되고, 나머지 구 노드들은 $C_{old}$에 방치됩니다 (비대칭 전파 모의).
- `enable_joint_consensus == true` (Joint Consensus 모드):
  - **Phase 1**: 모든 노드가 $C_{old,new}$ 공동 합의(`type: "JOINT"`) 설정으로 전환됩니다 (`joint_consensus_commits += 1`).
  - **Phase 2 (`complete_phase2 == true`)**: $C_{old,new}$ 커밋 후, 신규 노드들이 $C_{new}$ 단일 설정(`type: "SINGLE"`)으로 전환됩니다 (`final_cnew_commits += 1`). $C_{old}$에만 있고 $C_{new}$에 없는 노드들은 `decommissioned_nodes`에 등록되어 안전 퇴역합니다.

#### B. `SIMULATE_SPLIT_ELECTION` (분할 선출 시도)
- 후보자 A(`candidate_a`)와 득표 그룹 A(`voters_a`), 후보자 B(`candidate_b`)와 득표 그룹 B(`voters_b`)가 동시에 선출을 시도합니다.
- 각 후보자는 자신이 속한 활성 설정 기준 `check_quorum`을 검사합니다.
- **두 후보자가 동시에 쿼럼을 달성한 경우**:
  - `split_brain_detected = true`로 설정되고 `simultaneous_leaders`에 두 노드가 등록됩니다 (`CATASTROPHIC_SPLIT_BRAIN_TWO_LEADERS`).
- 한 후보자만 달성하거나 아무도 달성하지 못한 경우 안전성이 유지됩니다.

#### C. `CLIENT_WRITE` (클라이언트 데이터 쓰기)
- 리더(`leader_id`)가 지정된 승인 노드들(`acks`)로부터 응답을 받았을 때 쿼럼을 충족하는지 검사합니다.
- 쿼럼을 충족하면 `client_entries_committed`가 1 증가합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "enable_joint_consensus": true,
    "initial_nodes": [1, 2, 3]
  },
  "events": [
    {
      "type": "START_RECONFIG",
      "old_nodes": [1, 2, 3],
      "new_nodes": [1, 2, 3, 4, 5],
      "complete_phase2": true
    },
    {
      "type": "SIMULATE_SPLIT_ELECTION",
      "candidate_a": 1,
      "voters_a": [1, 2],
      "candidate_b": 5,
      "voters_b": [3, 4, 5]
    },
    {
      "type": "CLIENT_WRITE",
      "leader_id": 1,
      "entry": "tx_001",
      "acks": [1, 2, 3]
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "enable_joint_consensus": true,
  "metrics": {
    "reconfiguration_attempts": 1,
    "split_brain_detected": false,
    "simultaneous_leaders": [],
    "joint_consensus_commits": 1,
    "final_cnew_commits": 1,
    "client_entries_committed": 1,
    "decommissioned_nodes": [],
    "verdict": "JOINT_CONSENSUS_SAFE_RECONFIGURATION"
  },
  "timeline": [
    {
      "action": "ENTER_JOINT_CONSENSUS",
      "old_nodes": [1, 2, 3],
      "new_nodes": [1, 2, 3, 4, 5]
    }
  ]
}
```

### 최종 판정 (Verdict) 규칙
1. `CATASTROPHIC_SPLIT_BRAIN_TWO_LEADERS`: `split_brain_detected == true`인 경우 (동일 클러스터에 2명의 리더 동시 당선).
2. `JOINT_CONSENSUS_SAFE_RECONFIGURATION`: `enable_joint_consensus == true`이고 `joint_consensus_commits > 0`인 경우.
3. `STANDARD_CLUSTER_OPERATION`: 그 외의 경우 (재구성 없는 일반 클러스터 합의).
