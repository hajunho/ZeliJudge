# 문제 219: 분산 NoSQL Dynamo/Cassandra: Consistent Hash 토큰 링 vnode 데이터 편중(Skew)과 힌티드 핸드오프(Hinted Handoff) 폭풍 vs 전송량 쓰로틀링

## 1. 개요 (Incident Scenario)

글로벌 결제 및 대규모 유저 세션을 처리하는 분산 NoSQL 데이터베이스(Apache Cassandra / ScyllaDB / Dynamo 스타일) 클러스터를 운영하는 데이터 플랫폼 엔지니어링 팀은 두 가지 심각한 클러스터 안정성 장애에 직면했습니다.

클러스터는 마스터가 없는 피어-투-피어(Masterless P2P) 아키텍처로, 복제 계수(Replication Factor, $RF=3$)와 쿼럼 읽기/쓰기($CL=\text{QUORUM}$)를 통해 고가용성을 제공하도록 구성되어 있습니다.

그러나 다음과 같은 치명적인 운영 장애가 잇따라 발생했습니다:
1. **단일 토큰(Single Token) 배치로 인한 극심한 데이터 불균형(Data Skew)**:
   과거의 고전적 방식대로 물리 노드당 단 1개의 토큰(`num_tokens = 1`)만을 할당한 결과, 해시 링 상에서 특정 노드가 전체 토큰 범위의 25% 이상을 차지한 반면 다른 노드는 5%도 채 할당받지 못했습니다(불균형 비율 5배 이상). 그 결과 트래픽과 디스크 용량이 특정 노드에 집중되어 핫스팟 노드의 디스크가 조기 고갈되고 긴 GC 정체(STW)가 발생했습니다(`SEVERE_TOKEN_RING_DATA_SKEW`).
2. **복구된 노드를 향한 힌티드 핸드오프 폭풍(Hinted Handoff Storm & Flapping)**:
   노드 3이 일시적인 네트워크 장애로 5초간 다운된 동안, 클라이언트가 발행한 대량의 쓰기 요청을 처리하던 여러 코디네이터(Coordinator) 노드들은 쿼럼(2/3) 성공을 달성한 뒤 노드 3으로 전달하지 못한 변경 사항을 로컬 디스크에 **힌트(Hint)**로 기록했습니다.
   노드 3이 정상 복구(`UP`)되자마자, 모든 코디네이터 노드가 동시에 대역폭 제한 없이(`hint_throttle_in_kb = 0`) 수천 건의 힌트 뮤테이션을 쏟아부었습니다. 노드 3의 쓰기 큐(`MutationStage`, 용량 1000)가 즉시 오버플로우되어 뮤테이션을 드롭(`MutationDrop`)하기 시작했고, 노드 3은 다시 무응답 상태로 추락하며 다운되었습니다(`HINTED_HANDOFF_STORM_REPLICA_FLAPPING`).
3. **힌트 윈도우 초과로 인한 조용한 데이터 손실(Silent Data Loss)**:
   노드 장애가 설정된 힌트 보존 윈도우(`max_hint_window_in_ms`, 기본 30분)를 초과하여 지속되면, 코디네이터는 로컬 디스크 보호를 위해 힌트 저장을 중단합니다. 이로 인해 사후 복구 시 복제본 간 데이터 불일치가 영구적으로 잔존하게 됩니다(`SILENT_DATA_LOSS_HINT_EXPIRATION`).
4. **가상 노드(Vnodes) 및 전송량 쓰로틀링(Hint Streaming Throttling) 최적화**:
   노드당 가상 노드(`vnodes_per_node = 128`)를 도입하여 토큰 링의 데이터 점유율 편차(CV)를 5% 미만으로 균등화하고, 토큰 버킷 기반 힌트 스트리밍 쓰로틀링(`hint_throttle_kb_per_sec = 1024~2048 KB/s`)을 적용하여 복구된 레플리카의 큐 오버플로우 없이 100% 무손실 복구를 달성해야 합니다.

당신은 분산 스토리지 및 NoSQL 내부 아키텍처 전문가로서, Consistent Hashing 토큰 링 할당, Vnode 수에 따른 데이터 편중도 계산, 노드 장애 시 힌트 누적, 복구 시 힌티드 핸드오프 재생 및 쓰로틀링 제어를 정밀하게 모의(Simulation)하고 최종 진단 리포트를 생성하는 진단 엔진을 구현해야 합니다.

---

## 2. 아키텍처 및 상태 모델

```
 [Consistent Hash Token Ring (0 ~ 1,000,000)]
   - Node 1 ~ 6 각각 vnodes_per_node 개의 가상 토큰 배치
   - Token Range Ownership: 각 토큰 사이의 구간 길이 비율 산출

                        [Write Request: Key]
                                 │
                                 ▼
                     [Coordinator Node 선정]
                                 │
                 Hash(Key) ──► Ring에서 RF=3개 노드 탐색
                                 │
       ┌─────────────────────────┼─────────────────────────┐
       ▼                         ▼                         ▼
   [Replica 1 (UP)]          [Replica 2 (UP)]          [Replica 3 (DOWN)]
   MutationStage 큐 삽입     MutationStage 큐 삽입     Coordinator에 Hint 저장!
   (Write Success)           (Write Success)           (down_time <= max_hint_window)
       │                         │
       └─────────┬───────────────┘
                 ▼
         CL=QUORUM 달성! (Client ACK)

 ──► [Replica 3 정상화 (NODE_UP)]
       │
       ▼
   [Hinted Handoff Replay]
   - Unthrottled (throttle = 0)  ──► 큐 폭발 (Drop 발생) ──► Node Flapping (재다운!)
   - Throttled   (throttle > 0)  ──► 안전 전송 (Drop = 0) ──► 완벽 복구 달성!
```

### 시뮬레이션 동작 규격

1. **토큰 링 및 Vnode 점유율 계산**:
   - 링 전체 공간은 `RING_SIZE = 1,000,000`의 순환 정수 공간입니다.
   - 각 노드는 $v \in [0, \text{vnodes\_per\_node}-1]$에 대해 MD5 해시 기반 정수 토큰을 생성합니다:
     $$token = \text{int(MD5(f"{node}\_vnode\_{v}")[:8], 16)} \pmod{RING\_SIZE}$$
   - 링 위의 모든 토큰을 오름차순 정렬한 뒤, 인접 토큰 간의 구간 길이($(token_{i-1}, token_i]$)를 소유 노드에게 누적하여 노드별 점유율(`ownership_pct`)을 산출합니다.
   - 불균형 메트릭:
     $$\text{skew\_ratio} = \frac{\max(\text{ownership})}{\min(\text{ownership})}$$
     $$\text{CV (Coefficient of Variation)} = \frac{\sigma}{\mu} \times 100\%$$

2. **복제 및 힌트(Hinted Handoff) 축적**:
   - $RF=3$ (Replication Factor).
   - 쓰기 요청(키) 발생 시 해시 토큰 위치에서 시계 방향으로 첫 3개의 서로 다른 물리 노드를 레플리카로 선정합니다.
   - 대상 노드가 `UP` 상태이면 해당 노드의 `replica_mutation_queues`에 큐잉됩니다. (큐 용량 `queue_capacity = 1000`, 초과 시 드롭).
   - 대상 노드가 `DOWN` 상태이면:
     - 다운 지속 시간 $\le$ `max_hint_window_ms` (기본 30분): 코디네이터가 힌트로 저장 (`total_hints_created` 증가).
     - 다운 지속 시간 > `max_hint_window_ms`: 힌트 저장 거부 (`total_hints_expired` 증가).

3. **노드 복구 및 힌티드 핸드오프 재생 (Replay)**:
   - 노드가 `NODE_UP`으로 복구되면 코디네이터들이 보관 중인 힌트를 전달합니다.
   - `throttle_kb_per_sec <= 0` (쓰로틀링 해제):
     - 모든 힌트를 일시에 쏟아붓습니다.
     - 대상 노드의 큐 잔여 공간을 초과하면 오버플로우된 뮤테이션이 드롭(`dropped_mutations`)되고 노드가 다시 `DOWN` 상태로 플래핑(`replica_flapped = True`)합니다.
   - `throttle_kb_per_sec > 0` (쓰로틀링 적용):
     - 힌트가 제어된 속도로 안전하게 스트리밍되어 큐 드롭 없이 100% 재생 완료됩니다.

---

## 3. 입력 사양 (Input Specification)

JSON 형식으로 표준 입력(`sys.stdin`)을 통해 전달됩니다.

```json
{
  "config": {
    "nodes": ["node1", "node2", "node3", "node4", "node5", "node6"],
    "vnodes_per_node": 128,
    "replication_factor": 3,
    "hint_throttle_kb_per_sec": 1024.0,
    "max_hint_window_ms": 1800000.0,
    "skew_evaluation_only": false
  },
  "workload_events": [
    {"type": "NODE_DOWN", "node": "node3", "time_ms": 1000},
    {"type": "WRITE_BATCH", "coordinator": "node1", "count": 800, "time_ms": 2000},
    {"type": "WRITE_BATCH", "coordinator": "node2", "count": 800, "time_ms": 3000},
    {"type": "NODE_UP", "node": "node3", "time_ms": 5000}
  ]
}
```

- `nodes` (array): 클러스터 노드 이름 목록.
- `vnodes_per_node` (integer): 노드당 가상 노드 수 (1, 8, 128, 256 등).
- `hint_throttle_kb_per_sec` (number): 힌트 스트리밍 제한 속도 ($KB/s$, 0이면 무제한).
- `max_hint_window_ms` (number): 힌트 보존 최대 시간 ($ms$, 기본 1,800,000ms = 30분).
- `skew_evaluation_only` (boolean): 토큰 링 편중도 평가 전용 모드 여부.
- `workload_events` (array): 노드 장애/복구 및 쓰기 배치 이벤트 목록.

---

## 4. 출력 사양 (Output Specification)

JSON 형식으로 표준 출력(`sys.stdout`)에 출력합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_THROTTLED_HINTED_HANDOFF_RECOVERY",
  "metrics": {
    "vnodes_per_node": 128,
    "max_ownership_pct": 17.67,
    "min_ownership_pct": 15.72,
    "skew_ratio": 1.12,
    "coefficient_of_variation_pct": 3.43,
    "total_hints_created": 1190,
    "total_hints_replayed": 1190,
    "total_hints_expired": 0,
    "dropped_mutations": 0,
    "replica_flapped": false
  }
}
```

### 진단 판정(Verdict) 기준:
1. `skew_evaluation_only == true`:
   - `skew_ratio > 2.0` 또는 `coefficient_of_variation_pct > 25.0`: `"SEVERE_TOKEN_RING_DATA_SKEW"` (`status: "FAILED"`)
   - 그 외: `"BALANCED_VNODE_DATA_DISTRIBUTION"` (`status: "SUCCESS"`)
2. `replica_flapped == true` 또는 `dropped_mutations > 0`:
   - `"HINTED_HANDOFF_STORM_REPLICA_FLAPPING"` (`status: "FAILED"`)
3. `total_hints_expired > 0`:
   - `"SILENT_DATA_LOSS_HINT_EXPIRATION"` (`status: "FAILED"`)
4. `total_hints_replayed > 0` 및 `hint_throttle_kb_per_sec > 0`:
   - `"OPTIMAL_THROTTLED_HINTED_HANDOFF_RECOVERY"` (`status: "SUCCESS"`)
5. 그 외 정상 상태: `"NORMAL_CLUSTER_OPERATION"` (`status: "SUCCESS"`)
