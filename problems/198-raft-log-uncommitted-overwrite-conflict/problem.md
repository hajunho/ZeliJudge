# Raft 분산 합의: 비커밋 미동기화 로그 충돌 탐지와 팔로워 로그 강제 덮어쓰기(Log Overwrite) 복구

## 문제 배경 및 개요
분산 트랜잭션 및 스토리지 엔진(etcd, CockroachDB, TiKV, Consul)의 뼈대를 이루는 **Raft 합의 알고리즘(Raft Consensus Protocol)**에서 가장 정교하고 치명적인 장애 복구 시나리오는 **"네트워크 분할 및 리더 연속 크래시 이후 선출된 새 리더와 팔로워들 사이의 비커밋 로그 불일치(Log Discrepancy & Conflict Resolution)"** 상황입니다.

정상 상태에서는 리더의 로그가 팔로워들에게 순차적으로 복제되지만, 리더가 과반수(Majority Quorum) 복제를 완료하지 못한 채 급작스럽게 크래시하거나 네트워크 파티션으로 고립된 상태에서 클라이언트 쓰기 요청을 수락한 경우, 클러스터 내부에는 다음과 같은 복합적 로그 파편화가 발생합니다:
1. **지연된 팔로워 (Lagging Behind)**: 이전 리더들의 로그 항목(Entry) 일부를 받지 못해 로그 길이가 짧음.
2. **비커밋 충돌 로그 보유 (Uncommitted Divergent Entries)**: 이전 임기(Term)의 리더로부터 복제되었으나 과반수 커밋에 도달하지 못한 불일치 로그가 팔로워 디스크에 잔류.
3. **다중 임기 파편화 (Multi-Term Fragmentation)**: 여러 차례의 리더 교체로 인해 임기 2, 3, 5, 6 등 서로 다른 임기의 비커밋 엔트리들이 뒤섞여 존재 (Raft 논문 Figure 7 참조).

새로운 리더는 선출 즉시 팔로워들과의 일치점(`matchIndex`)을 찾아내고, **커밋되지 않은 불일치 로그를 단호히 잘라내어 버린(Truncate) 뒤 자신의 정규 로그로 강제 덮어쓰기(Log Overwrite)**해야 합니다.
그러나 순진한 나이브 역추적(`NAIVE_DECREMENT`, 1칸씩 `nextIndex` 감소)은 로그 차이가 큰 대규모 분산 클러스터에서 극심한 RTT 왕복 지연 폭풍(Round-Trip Time Storm)을 유발하여 시스템 장애 복구를 수십 초 이상 지연시킵니다.
반면 Raft 논문 섹션 5.3의 **고속 역추적 최적화(`FAST_BACKTRACKING`)** 기법은 팔로워의 충돌 임기(`conflictTerm`)와 최초 발생 인덱스(`conflictIndex`) 힌트를 활용하여, 단 한두 번의 RTT만으로 임기 단위 통째 건너뛰기를 수행합니다.

또한 Raft 안전성 보장 규칙(Raft Safety Section 5.4.2)에 따라:
- 이미 커밋된 로그(`index <= commit_index`)는 어떠한 경우에도 덮어쓰거나 잘라낼 수 없으며(`FATAL_COMMITTED_LOG_OVERWRITE`),
- 이전 임기(Older Term)의 엔트리가 과반수에 복제되어 있더라도, **현재 리더의 임기(Current Term)에서 생성된 엔트리가 과반수에 도달하기 전까지는 이전 임기 로그를 독자적으로 커밋할 수 없습니다 (Figure 8 Safety Rule)**.

당신은 Raft 합의 엔진의 코어 프로토콜 엔지니어로서, 리더와 팔로워 간의 로그 불일치 탐지, 고속 역추적(Fast Backtracking), 안전한 비커밋 로그 Truncation/Overwrite, 그리고 과반수 쿼럼 커밋 전진 엔진을 완벽하게 구현해야 합니다.

---

## 입력 형식
입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:
```json
{
  "cluster": {
    "nodes": ["N1", "N2", "N3", "N4", "N5"],
    "leader_id": "N1",
    "leader_term": 8,
    "leader_commit": 4,
    "leader_log": [
      {"index": 1, "term": 1, "cmd": "SET x=1"},
      ...
    ],
    "followers": {
      "N2": {
        "current_term": 6,
        "commit_index": 4,
        "log": [ ... ]
      }
    }
  },
  "new_proposals": ["SET final=999"],
  "strategy": "FAST_BACKTRACKING",
  "options": {
    "max_rtt_limit": 50
  }
}
```

- `cluster.nodes`: 클러스터에 참여하는 전체 노드 ID 리스트 ($N$개 노드, 과반수 쿼럼 $Q = \lfloor N/2 \rfloor + 1$).
- `cluster.leader_id`: 현재 합법적으로 선출된 리더 노드 ID.
- `cluster.leader_term`: 현재 리더의 임기 (정수).
- `cluster.leader_commit`: 리더의 초기 커밋 인덱스 (`leaderCommit`).
- `cluster.leader_log`: 리더가 보유한 정규 로그 엔트리 배열 (`index`, `term`, `cmd`).
- `cluster.followers`: 각 팔로워 노드의 초기 상태 (`current_term`, `commit_index`, `log`).
- `new_proposals`: 리더가 현재 임기(`leader_term`)에서 새로 제안(Propose)하여 로그 끝에 추가할 클라이언트 커맨드 리스트.
- `strategy`: 역추적 전략 (`"FAST_BACKTRACKING"` 또는 `"NAIVE_DECREMENT"`).
- `options.max_rtt_limit`: 팔로워당 허용되는 최대 AppendEntries 왕복 RTT 한도 (초과 시 `RTT_EXCEEDED` 판정).

---

## 출력 형식
표준 출력(Standard Output)으로 복구 및 동기화 시뮬레이션 결과를 JSON 형태로 출력합니다:
```json
{
  "strategy_used": "FAST_BACKTRACKING",
  "leader_metrics": {
    "leader_id": "N1",
    "leader_term": 8,
    "initial_commit_index": 4,
    "final_commit_index": 11,
    "total_log_entries": 11,
    "committed_proposals": ["SET final=999"],
    "quorum_size": 3
  },
  "followers": {
    "N2": {
      "status": "SYNCHRONIZED",
      "rtt_rounds": 2,
      "truncated_entries_count": 0,
      "final_log_length": 11,
      "commit_index": 11,
      "match_index": 11,
      "last_log_term": 8
    },
    "N3": {
      "status": "SYNCHRONIZED",
      "rtt_rounds": 3,
      "truncated_entries_count": 8,
      "final_log_length": 11,
      "commit_index": 11,
      "match_index": 11,
      "last_log_term": 8
    }
  },
  "cluster_summary": {
    "total_cluster_rtts": 5,
    "consensus_status": "HEALTHY",
    "all_synchronized": true
  }
}
```

- 만약 어떤 팔로워라도 이미 커밋된 인덱스(`idx <= commit_index`)에 대해 충돌이 발생하면:
  - 해당 팔로워의 `status`는 `"SAFETY_VIOLATION"`, `violation_reason` 명시.
  - `cluster_summary.consensus_status`는 `"FATAL_SAFETY_VIOLATION"`.
- 만약 RTT 한도를 초과하면:
  - 해당 팔로워의 `status`는 `"RTT_EXCEEDED"`.
  - `cluster_summary.consensus_status`는 `"PARTIAL_CONVERGENCE"`.

---

## 판정 기준 (Verdict Rules)
1. **정확한 일치점 탐색**: `prevLogIndex`와 `prevLogTerm`을 검증하여 리더와 팔로워 로그가 일치하는 지점을 완벽히 찾아내어야 합니다.
2. **무자비하고 안전한 Truncation**: 일치점 이후 존재하는 팔로워의 모든 비커밋 상충 로그를 정확히 잘라내고(`truncated_entries_count`), 리더의 엔트리를 이어 붙여 로그 동일성을 보장해야 합니다.
3. **Raft 불변식 수호**: 이미 커밋된 엔트리(`<= commit_index`)에 대한 덮어쓰기 시도를 감지하여 즉시 거절하고 시스템 패닉을 보고해야 합니다.
4. **Figure 8 쿼럼 커밋 법칙**: 오직 현재 임기(`leader_term`)의 로그가 과반수에 도달했을 때만 커밋 인덱스를 전진시키고, 동기화된 팔로워들에게 전파해야 합니다.
