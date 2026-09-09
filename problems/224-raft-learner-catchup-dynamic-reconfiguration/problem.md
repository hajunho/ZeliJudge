# 문제 224: 분산 합의(Distributed Consensus): Raft 비투표 학습자(Non-Voting Learner) 노드와 동적 쿼럼 재구성(Dynamic Reconfiguration) 및 가용성 절벽(Availability Cliff) 방어

## 1. 개요 (Incident Scenario)

수만 대의 마이크로서비스 컨테이너와 쿠버네티스(Kubernetes) 컨트롤 플레인의 상태를 단일 진실 공급원(Single Source of Truth)으로 관리하는 분산 키-값 저장소(etcd / TiKV / CockroachDB / HashiCorp Consul 계열) 엔지니어링 팀은 클러스터 가용성을 높이기 위해 기존 3노드($N_1, N_2, N_3$) Raft 합의 그룹을 5노드로 동적 확장(Scale-out)하는 인프라 작업을 수행했습니다.

기존 3노드 클러스터의 과반수 쿼럼(Quorum)은 $\lfloor 3/2 \rfloor + 1 = 2$로, 노드 1대의 장애(하드웨어 크래시, 네트워크 단절)를 완벽히 견딜 수 있는 상태였습니다.

그러나 신규 노드를 추가하는 과정에서 Raft 합의 프로토콜의 특성을 간과하여 다음과 같은 세 가지 치명적인 가용성 절벽(Availability Cliff) 및 프로모션 장애가 연쇄적으로 발생했습니다:

1. **콜드 노드 즉시 투표권 부여로 인한 쿼럼 상실 및 쓰기 전면 중단(Availability Cliff Collapse)**:
   운영자가 아무런 로그도 없는 빈 노드 $N_4$(`match_index = 0`)를 곧바로 정식 투표 멤버(`VOTER`)로 클러스터에 추가(`ConfChangeAddNode(VOTER)`)했습니다.
   투표 멤버가 4대로 늘어나면서 필수 쿼럼은 즉시 **2대에서 3대($\lfloor 4/2 \rfloor + 1 = 3$)로 증가**했습니다.
   신규 노드 $N_4$는 수십만 건의 과거 로그 스냅샷을 전송받느라 바빠 신규 커밋에 전혀 투표할 수 없는 상태였습니다. 이 와중에 기존 노드 $N_3$이 일상적인 Go 런타임 GC 정체(STW)나 네트워크 깜빡임으로 3초간 응답하지 못하자, 정상 응답 가능한 투표 노드는 $N_1, N_2$ 단 2대뿐이었습니다.
   필수 쿼럼(3대)을 충족하지 못해 **클러스터 전체의 모든 쓰기 트랜잭션이 전면 동결(Total Write Freeze)**되었고, 쿠버네티스 API 서버가 전면 마비되는 대재앙(`PREMATURE_VOTING_MEMBER_QUORUM_COLLAPSE`)이 발생했습니다.

2. **쓰기 유입 속도 과다로 인한 학습자 동기화 기아 루프(Learner Catch-Up Starvation Loop)**:
   이를 방지하기 위해 신규 노드를 투표권이 없는 **학습자(Non-Voting Learner)**로 먼저 참여시켰습니다.
   학습자는 로그를 복제받지만 쿼럼 계산에 포함되지 않아 클러스터 가용성을 해치지 않습니다. 리더는 학습자의 지연 격차(Gap)가 임계치(`catchup_threshold_entries = 100`) 이하로 좁혀질 때까지 다단계 라운드($R_1, R_2, \dots$) 동기화를 진행합니다.
   그러나 리더의 신규 트랜잭션 쓰기 유입 속도(`leader_write_rate = 3,500 entries/s`)가 학습자의 네트워크 수신 및 디스크 기록 속도(`learner_ingest_rate = 2,800 entries/s`)를 초과하자, 매 라운드가 진행될수록 격차가 좁혀지기는커녕 오히려 누적 확대되어 최대 라운드(`max_catchup_rounds`)를 초과하고 프로모션이 영구 실패하는 기아 상태(`LEARNER_CATCHUP_STARVATION_LOOP`)가 초래되었습니다.

3. **비투표 학습자(Learner)와 단계적 라운드 수렴을 통한 안전한 원자적 프로모션**:
   Diego Ongaro(Raft 창시자) 논문(Section 4.2.1) 및 etcd 3.4+ 설계에 따라, 사전 스냅샷을 적용하고 학습자가 이전 라운드의 격차를 기하급수적으로 좁히는 다단계 수렴 조건($\text{write\_rate} < \text{ingest\_rate}$)을 검증한 뒤, 임계치 이하 도달 시점에 단일 서버 멤버십 변경(`ConfChangeAddNode`)을 통해 투표 노드로 원자적 승격(`OPTIMAL_LEARNER_PROMOTION_DYNAMIC_MEMBERSHIP`)시켜야 합니다.

당신은 분산 합의 및 고가용성 인프라 엔지니어로서, Raft 클러스터의 동적 멤버십 변경 시 투표 노드 직접 추가의 쿼럼 붕괴 위험과 학습자 노드의 다단계 라운드 수렴 과정을 시뮬레이션하고 클러스터의 안전성을 검증하는 진단 엔진을 구현해야 합니다.

---

## 2. 아키텍처 및 상태 모델

```
 [Naive Direct Addition: The Availability Cliff]
  Cluster: [N1, N2, N3] (Voters=3, Quorum=2). Can tolerate 1 failure.
                          │
                          ▼ Admin adds N4 directly as VOTER!
  Cluster: [N1, N2, N3, N4] (Voters=4, Quorum=3).
  * N4 is COLD (match_index = 0, cannot vote yet!)
  * If N3 has a network hiccup: Only [N1, N2] responsive (2 < 3 Quorum)!
  ===> CLUSTER LOSES WRITE AVAILABILITY! ALL WRITES FREEZE!

 ───────────────────────────────────────────────────────────────────────────

 [Safe Non-Voting Learner Progression (etcd 3.4+ / Ongaro Thesis)]
  Step 1: Add N4 as LEARNER (Non-Voting Observer).
          Voters=[N1, N2, N3] (Quorum remains 2! N3 failure tolerated!).

  Step 2: Multi-Round Log Catch-Up (Geometric Convergence):
          Round 1: N4 replicates Gap 0 (5000 entries) in t1=1.67s.
                   Leader accepts new writes: Gap 1 = 833 entries.
          Round 2: N4 replicates Gap 1 in t2=0.28s.
                   Leader accepts new writes: Gap 2 = 139 entries.
          Round 3: N4 replicates Gap 2 in t3=0.05s.
                   Leader accepts new writes: Gap 3 = 23 entries <= Threshold (100)!

  Step 3: Atomic Promotion to VOTER via ConfChangeAddNode.
          N4 is warm! Votes immediately! ZERO AVAILABILITY LOSS!
```

### 시뮬레이션 동작 규격

1. **클러스터 및 재구성 설정**:
   - `add_as_learner_first`: 신규 노드를 투표자 추가 전 학습자로 먼저 참여시킬지 여부(bool)
   - `catchup_threshold_entries`: 프로모션을 승인할 최대 허용 잔여 로그 격차(기본 100개)
   - `max_catchup_rounds`: 최대 허용 동기화 라운드 수 (기본 10회)
   - `initial_voters`: 기존 투표 노드 목록 (예: `["N1", "N2", "N3"]`)
   - `commit_index`: 리더의 현재 커밋 인덱스
   - `snapshot_applied_index`: 학습자에게 사전 주입된 스냅샷 인덱스 (없으면 0)
   - `node_to_add`: 추가 대상 노드 식별자 (예: `"N4"`)
   - `concurrent_node_failure`: 확장 진행 중 우발적으로 발생한 기존 노드 장애 (예: `"N3"` 또는 `null`)

2. **직접 투표자 추가 (`add_as_learner_first == false`)**:
   - 신규 노드를 즉시 `current_voters`에 추가합니다.
   - 신규 필수 쿼럼: $\text{new\_quorum} = \lfloor |\text{voters}| / 2 \rfloor + 1$
   - 신규 노드는 `match_index = 0`이므로 투표할 수 없습니다.
   - 가용 응답 노드 수: 기존 노드 중 장애 노드(`concurrent_node_failure`)를 제외한 수.
   - 만약 가용 응답 노드 수가 `new_quorum` 미만이면 쿼럼 붕괴 발생:
     - `status = "FAILED"`, `verdict = "PREMATURE_VOTING_MEMBER_QUORUM_COLLAPSE"`
   - 장애 노드가 없어 가용 노드가 쿼럼 이상이면 성공하나 위험 경고:
     - `status = "SUCCESS"`, `verdict = "VOTER_ADDED_WITHOUT_LEARNER_RISKY"`

3. **학습자 기반 단계적 동기화 (`add_as_learner_first == true`)**:
   - 학습자의 네트워크가 단절(`learner_network_status == "PARTITIONED"`)되어 있으면:
     - `status = "FAILED"`, `verdict = "LEARNER_UNREACHABLE_TIMEOUT"` (기존 쿼럼은 영향 없음).
   - 초기 격차: $\text{current\_gap} = \text{commit\_index} - \text{snapshot\_applied\_index}$
   - 동기화 라운드 순회 ($r = 1, 2, \dots, \text{max\_catchup\_rounds}$):
     - 라운드 소요 시간: $t_r = \text{current\_gap} / \text{learner\_ingest\_rate}$
     - 학습자 매칭 인덱스 증가: $\text{learner\_match\_index} += \text{current\_gap}$
     - 해당 시간 동안 리더에 유입된 신규 쓰기: $\text{new\_writes} = \lfloor \text{leader\_write\_rate} \times t_r \rfloor$
     - 차기 라운드 격차 갱신: $\text{current\_gap} = \text{new\_writes}$
     - 만약 $\text{current\_gap} \le \text{catchup\_threshold\_entries}$ 이면 **동기화 수렴 완료(Caught Up)**!
   - 최대 라운드 도달 시까지 수렴하지 못하면:
     - `status = "FAILED"`, `verdict = "LEARNER_CATCHUP_STARVATION_LOOP"`
   - **원자적 프로모션(Atomic Promotion)**:
     - 학습자를 투표자로 정식 승격 (`current_voters.append(node_to_add)`).
     - 승격된 노드는 이미 최신 로그를 가졌으므로 즉시 투표 가능합니다.
     - 기존 노드 중 하나(`concurrent_node_failure`)가 죽더라도 신규 노드가 투표에 참여하므로 쿼럼을 완벽 유지합니다:
       - `status = "SUCCESS"`, `verdict = "OPTIMAL_LEARNER_PROMOTION_DYNAMIC_MEMBERSHIP"`

---

## 3. 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "add_as_learner_first": true,
    "catchup_threshold_entries": 100,
    "max_catchup_rounds": 10
  },
  "cluster": {
    "initial_voters": ["N1", "N2", "N3"],
    "commit_index": 50000,
    "snapshot_applied_index": 45000,
    "node_to_add": "N4",
    "concurrent_node_failure": "N3"
  },
  "replication": {
    "leader_write_rate_entries_per_sec": 500.0,
    "learner_ingest_rate_entries_per_sec": 3000.0,
    "learner_network_status": "HEALTHY"
  }
}
```

---

## 4. 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_LEARNER_PROMOTION_DYNAMIC_MEMBERSHIP",
  "metrics": {
    "add_as_learner_first": true,
    "final_voters_count": 4,
    "required_quorum": 3,
    "available_responsive_voters": 3,
    "catchup_rounds_completed": 3,
    "final_learner_match_index": 50971,
    "quorum_availability_maintained": true
  }
}
```
