# Problem 212: 각 노드는 아무 사이클도 없는데 분산 트랜잭션 전체가 멈췄다고요?!: 분산 교착 상태(Distributed Deadlock) 탐지와 Chandy-Misra-Haas(CMH) 에지 추적(Edge-Chasing) 프로브 알고리즘 vs 중앙 집중식 WFG 유령 데드락 (Distributed Deadlock Detection: Chandy-Misra-Haas Edge-Chasing Probe vs Centralized WFG Coordinator & Phantom Deadlocks)

## 문제 배경 및 개요

대규모 글로벌 분산 데이터베이스(CockroachDB, Google Spanner, TiDB 등)를 운영하는 분산 스토리지 플랫폼 팀은 블랙 프라이데이 결제 트래픽 피크 타임에 원인을 알 수 없는 **"분산 샤드 동시 결제 동결(Distributed Transaction Freeze) 및 유령 데드락 참사"**를 겪었습니다.

단일 노드 환경에서는 커널이나 RDBMS가 메모리 상의 대기 그래프(Wait-For Graph, WFG)를 탐색하여 순환 참조($T_A \to T_B \to T_A$)를 쉽게 찾아낼 수 있습니다. 그러나 여러 물리 노드(샤드)에 걸쳐 데이터 행(Row)을 잠그는 분산 트랜잭션 환경에서는 상상을 초월하는 교착 상태가 발생합니다:

```
[각 노드의 로컬 뷰: 어디에도 사이클이 없다! (모두 정상 비순환 DAG)]
Node 1 (Shard 1):  T3 ──── 대기 ────► T1 (R1 락 보유)   [비순환 단방향 대기]
Node 2 (Shard 2):  T1 ──── 대기 ────► T2 (R2 락 보유)   [비순환 단방향 대기]
Node 3 (Shard 3):  T2 ──── 대기 ────► T3 (R3 락 보유)   [비순환 단방향 대기]

===> 각 노드의 로컬 DB 모니터링: "우리 노드에는 데드락 사이클이 전혀 없습니다!"
===> 그러나 클러스터 전역(Global View)에서는:
     T1 (Node 1) ───대기───► T2 (Node 2) ───대기───► T3 (Node 3) ───대기───► T1 (Node 1)
     전체 클러스터가 3자 분산 교착 상태(Distributed Deadlock Cycle)에 빠져 100% 동결!
```

인프라 팀은 이를 해결하기 위해 모든 샤드의 락 대기 상태를 중앙 서버로 모아 전역 WFG를 그리는 **중앙 집중식 WFG 코디네이터(Centralized WFG Coordinator)**를 도입했습니다. 그러나 네트워크 지연과 비동기 메시지 도착 순서 왜곡으로 인해 더 끔찍한 재앙이 터졌습니다:
- $T_2$가 이미 락을 정상 해제하고 트랜잭션을 끝냈음에도 불구하고,
- 네트워크 지연으로 인해 $T_2$의 락 해제 메시지보다 이전 대기 등록 메시지가 먼저 수합되면서,
- 코디네이터가 존재하지도 않는 가짜 사이클을 감지하고 무고한 정상 트랜잭션을 강제 롤백시켜 버리는 **유령 교착 상태(Phantom Deadlock)** 참사가 속출했습니다!

이를 원천 해결하기 위해 고안된 분산 시스템의 고전적이고 우아한 해법이 바로 **Chandy-Misra-Haas(CMH) 에지 추적(Edge-Chasing) 프로브 알고리즘**입니다.

CMH 알고리즘은 중앙 코디네이터 없이, 대기 상태에 빠진 트랜잭션이 활성 대기 에지를 따라 **프로브 메시지(`probe(initiator, sender, receiver)`)**를 전진(Chasing)시키며, 만약 프로브가 최초 발신자(`initiator`)에게 다시 되돌아오면 진정한 분산 사이클이 형성되었음을 100% 증명하고 희생자(Victim)를 선정해 즉각 데드락을 해소합니다.

당신은 분산 트랜잭션 엔진 엔지니어로서, 중앙 집중식 코디네이터 방식과 Chandy-Misra-Haas 에지 추적 방식을 시뮬레이션하여 분산 교착 상태를 정확히 진단하고 유령 데드락을 방어하는 감지 엔진을 구현해야 합니다.

---

## 2대 탐지 모드 동작 규칙

### 1. `CHANDY_MISRA_HAAS_EDGE_CHASING` (CMH 분산 에지 추적 모드)
- 트랜잭션 $T_i$가 다른 트랜잭션 $T_j$가 보유한 락으로 인해 차단(`BLOCKED`)되는 즉시, 프로브 메시지 `probe(initiator: T_i, sender: T_i, receiver: T_j)`를 발송합니다 (`probes_initiated += 1`).
- 동일 노드 내 대기인 경우 네트워크 지연은 $0\,\text{ms}$, 서로 다른 물리 노드 간 대기인 경우 `probe_network_delay_ms` 지연 후 수신됩니다.
- 수신 트랜잭션 $T_j$가 활성(`ACTIVE`) 상태이거나 이미 종료된 경우, 경로 상에 교착 상태가 없으므로 프로브는 즉시 폐기됩니다.
- 수신 트랜잭션 $T_j$가 또 다른 트랜잭션 $T_k$를 대기하고 있는 경우:
  - 만약 $T_k == \text{initiator}$ 라면: **분산 교착 상태(Distributed Deadlock Cycle) 감지!**
    - 사이클 구성원 노드가 모두 같으면 `local_cycles_detected += 1`, 다른 노드가 섞여 있으면 `distributed_cycles_detected += 1`.
    - 희생자 선정 정책(`victim_policy`)에 따라 희생자 트랜잭션을 선정하여 강제 롤백(`ABORTED`)하고, 보유 락을 즉시 해제하여 대기 큐의 후속 트랜잭션을 깨웁니다.
  - 그렇지 않고 방문 경로에 $T_k$가 없다면: 프로브를 전진 전달(`probes_forwarded += 1`)하여 $T_k$의 호스트 노드로 `probe(initiator, sender: T_j, receiver: T_k)`를 발송합니다.
- 평가 판정: 사이클이 성공적으로 해소되면 `DEADLOCK_DETECTED_CYCLE_RESOLVED`, 사이클 없이 모든 트랜잭션이 완료되면 `NO_DEADLOCK_EXECUTION_COMPLETED`.

### 2. `CENTRALIZED_WFG_COORDINATOR` (중앙 집중식 WFG 코디네이터 모드)
- 각 노드에서 락 대기가 발생하거나 해제될 때마다 중앙 코디네이터에게 에지 추가(`ADD_EDGE`) 및 에지 삭제(`DEL_EDGE`) 알림을 보냅니다 (`coordinator_messages_sent += 1`).
- 이 알림 메시지는 `coordinator_network_delay_ms`만큼의 전송 지연을 겪습니다.
- 코디네이터는 `coordinator_interval_ms` 주기마다 자신이 수신한 에지들로 전역 그래프를 구성하고 DFS를 수행해 사이클을 탐지합니다.
- **유령 교착 상태(Phantom Deadlock) 발생 메커니즘**:
  - 트랜잭션이 이미 락을 해제(`RELEASE_LOCK`)했으나 해당 삭제 메시지가 지연되는 동안 코디네이터 주기가 도래하면, 코디네이터는 이미 사라진 과거의 대기 에지를 보고 가짜 사이클을 감지합니다.
  - 실제 클러스터 상태에서는 교착 상태가 아님에도 무고한 트랜잭션을 강제 롤백(`phantom_deadlocks_detected += 1`)시키는 대형 장애가 발생합니다.
- 평가 판정: 유령 데드락 발생 시 `PHANTOM_DEADLOCK_FALSE_ABORT` (`status: FAILED`), 정상적인 실제 데드락만 해소된 경우 `DEADLOCK_DETECTED_CYCLE_RESOLVED`.

---

## 희생자 선정 정책 (`victim_policy`)
1. **`YOUNGEST`**: 사이클에 연루된 블록 트랜잭션 중 시작 시각(`start_time`)이 가장 늦은 트랜잭션을 희생자로 선정 (동률 시 우선순위 숫자, 트랜잭션 ID 순 정렬).
2. **`LOWEST_PRIORITY`**: 우선순위 번호(`priority`)가 가장 큰(즉, 우선순위가 가장 낮은) 트랜잭션을 희생자로 선정.

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mode": "CHANDY_MISRA_HAAS_EDGE_CHASING",
    "victim_policy": "YOUNGEST",
    "coordinator_interval_ms": 100,
    "coordinator_network_delay_ms": 60,
    "probe_network_delay_ms": 5
  },
  "transactions": [
    {"tx_id": "T1", "node": "node-1", "priority": 10, "start_time": 100},
    {"tx_id": "T2", "node": "node-2", "priority": 20, "start_time": 120},
    {"tx_id": "T3", "node": "node-3", "priority": 30, "start_time": 140}
  ],
  "resources": [
    {"node": "node-1", "resource_id": "R1"},
    {"node": "node-2", "resource_id": "R2"},
    {"node": "node-3", "resource_id": "R3"}
  ],
  "events": [
    {"timestamp": 10, "action": "ACQUIRE_LOCK", "tx_id": "T1", "node": "node-1", "resource_id": "R1"},
    {"timestamp": 20, "action": "ACQUIRE_LOCK", "tx_id": "T2", "node": "node-2", "resource_id": "R2"},
    {"timestamp": 30, "action": "ACQUIRE_LOCK", "tx_id": "T3", "node": "node-3", "resource_id": "R3"},
    {"timestamp": 40, "action": "ACQUIRE_LOCK", "tx_id": "T1", "node": "node-2", "resource_id": "R2"},
    {"timestamp": 50, "action": "ACQUIRE_LOCK", "tx_id": "T2", "node": "node-3", "resource_id": "R3"},
    {"timestamp": 60, "action": "ACQUIRE_LOCK", "tx_id": "T3", "node": "node-1", "resource_id": "R1"},
    {"timestamp": 100, "action": "COMMIT", "tx_id": "T2"},
    {"timestamp": 120, "action": "COMMIT", "tx_id": "T1"}
  ]
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 진단 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "DEADLOCK_DETECTED_CYCLE_RESOLVED",
  "mode": "CHANDY_MISRA_HAAS_EDGE_CHASING",
  "metrics": {
    "total_events_processed": 8,
    "local_cycles_detected": 0,
    "distributed_cycles_detected": 1,
    "phantom_deadlocks_detected": 0,
    "probes_initiated": 3,
    "probes_forwarded": 1,
    "coordinator_messages_sent": 0,
    "aborted_transactions": [
      "T3"
    ],
    "committed_transactions": [
      "T2",
      "T1"
    ],
    "average_resolution_latency_ms": 10.0
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`PHANTOM_DEADLOCK_FALSE_ABORT`**: 중앙 코디네이터 모드에서 네트워크 지연으로 인해 이미 해제된 락 정보를 오인하여 무고한 정상 트랜잭션을 강제 롤백시킨 경우 (`status: FAILED`).
2. **`DEADLOCK_DETECTED_CYCLE_RESOLVED`**: 실제 분산 또는 로컬 데드락 사이클을 올바르게 감지하고, 적절한 희생자를 선정하여 롤백함으로써 클러스터 교착 상태를 정상 해소한 경우 (`status: SUCCESS`).
3. **`NO_DEADLOCK_EXECUTION_COMPLETED`**: 대기 관계가 존재했으나 사이클이 형성되지 않아 모든 트랜잭션이 롤백 없이 안전하게 커밋 완료된 경우 (`status: SUCCESS`).
4. **`UNRESOLVED_EXECUTION_STALL`**: 데드락이 감지되지 않아 트랜잭션들이 영구 대기 상태에 갇힌 경우 (`status: FAILED`).
