# Problem 206: 네트워크 10ms 지연에 왜 Raft 처리량이 100건으로 곤두박질쳐요?!: 분산 합의 Raft: Stop-and-Wait 복제 병목 vs Pipelined 파이프라인 복제와 In-flight 윈도우 흐름 제어 (Raft Consensus: Stop-and-Wait vs Pipelined Replication & In-flight Window Flow Control)

## 문제 배경 및 개요

대규모 클라우드 네이티브 분산 키-값 저장소(etcd, CockroachDB, TiKV, Consul) 및 분산 메타데이터 코디네이터를 운영하는 플랫폼 인프라 엔지니어링 팀은 멀티 가용 영역(Multi-AZ) 및 리전 간(Cross-Region) 환경에서 Raft 분산 합의 클러스터를 확장하는 과정에서 심각한 **처리량 절벽(Throughput Collapse) 및 연쇄 거절 폭풍(Cascading Rejection Storm)** 현상을 맞닥뜨렸습니다.

로컬 개발 환경(단일 머신 또는 동일 랙, $RTT < 0.1\,\text{ms}$)에서 초당 50,000건 이상의 쓰기를 거뜬히 처리하던 Raft 리더 노드가, 네트워크 왕복 지연시간이 $10\,\text{ms}$인 멀티 AZ 환경에 배포되자마자 **초당 쓰기 처리량이 고작 100건 안팎으로 99.8% 곤두박질치며 시스템 전체가 마비**되었습니다.

```
[클라이언트 대량 쓰기 유입: 10,000 req/s]
          │
          ▼
   ┌───────────────┐
   │  Raft Leader  │
   │  (Log Buffer) │
   └───────┬───────┘
           │
           ├── [Stop-and-Wait 복제 방식]
           │   1개 AppendEntries 전송 후 응답 올 때까지 파이프라인 동결! (RTT = 10ms)
           │   ==> 1초에 최대 100회 왕복 한계! (100 batches/s x 1 = 100~500 req/s 병목!)
           │
           ├── [나이브 Unbounded Pipelining]
           │   응답 대기 없이 수십 개 RPC를 소켓에 마구잡이 폭격!
           │   ==> 팔로워 100ms GC 정지/디스크 스톨 시 소켓 버퍼 폭발 (Buffer Bloat)
           │   ==> 로그 충돌 1건 발생 시 미확인 In-flight RPC 30건이 전부 연쇄 거절! (Cascading Rejection Storm)
           │
           └── [Production-grade Pipelined Flow Control (etcd/raft 표준)]
               StateProbe (1회 탐색) <-> StateReplicate (고속 파이프라인)
               In-flight 슬라이딩 윈도우(max_inflight=8)로 소켓 버퍼링 및 BDP 최적 포화!
               거절 발생 시 즉시 StateProbe 강등 & In-flight 전량 파기(Wipeout)로 폭풍 100% 차단!
```

이 참사의 근본 원인은 Raft 논문 원형의 **정지-대기(Stop-and-Wait)** 복제 모델에 있었습니다. 리더는 팔로워에게 `AppendEntries` RPC를 한 번 전송한 뒤 팔로워의 승인 응답(`AppendEntriesResponse`)이 도착할 때까지 다음 RPC 전송을 차단합니다. 그 결과 대역폭-지연 곱(Bandwidth-Delay Product, BDP)이 완전히 낭비되며, 네트워크 RTT의 역수($1/\text{RTT}$)가 시스템 전체 처리량의 물리적 상한선이 됩니다.

이를 해결하고자 고안된 **비제한 파이프라이닝(Unbounded Pipelining)**은 응답을 기다리지 않고 새 로그가 들어오는 족족 RPC를 연속 발송합니다. 그러나 이 방식은 팔로워의 일시적 정지(JVM GC Pause, 디스크 fsync 스톨) 시 리더의 소켓 송신 버퍼와 메모리를 폭발시키며, 첫 번째 RPC에서 로그 불일치(`prevLogIndex/prevLogTerm` 불일치)가 발생할 경우 네트워크 파이프에 이미 흘러간 뒤따르는 수십 개의 미확인 RPC가 **연쇄적으로 전부 거절당하는 재앙적인 Rejection Storm**을 일으킵니다.

etcd의 핵심 합의 엔진인 `go.etcd.io/raft`와 TiKV의 `raft-rs`는 이를 해결하기 위해 **이중 상태 머신(`StateProbe` vs `StateReplicate`)과 In-flight 슬라이딩 윈도우 흐름 제어(Inflight Sliding Window Flow Control)**를 구현했습니다.

당신은 분산 합의 엔진의 코어 아키텍트로서, 3대 복제 정책(Stop-and-Wait, Unbounded Pipelining, Pipelined Flow Control)을 정밀하게 시뮬레이션하고 분산 로그 합의 성능과 안전성을 평가하는 벤치마크 진단기를 완성해야 합니다.

---

## 3대 Raft 로그 복제 정책 명세

### 1. `STOP_AND_WAIT` (정지-대기 복제 모드)
- 리더는 팔로워별로 단 하나의 RPC만 네트워크에 띄울 수 있습니다 (`is_waiting_ack == True`인 동안 추가 전송 차단).
- 팔로워로부터 응답이 돌아와야만 다음 로그 배치를 전송합니다.
- 네트워크 RTT가 $10\,\text{ms}$이고 로그 배치가 쌓여 있어도 $1\,\text{RTT}$당 $1$개의 배치만 처리되므로, 클라이언트 요청이 큐에 누적되어 커밋 지연시간(Commit Latency)이 선형적으로 폭증합니다.
- 평가 판정(Verdict): 평균 지연시간 $\ge 30\,\text{ms}$ 또는 최대 지연시간 $\ge 50\,\text{ms}$ 시 `STOP_AND_WAIT_THROUGHPUT_COLLAPSE`, 가벼운 워크로드인 경우 `STOP_AND_WAIT_NOMINAL`.

### 2. `UNBOUNDED_PIPELINING` (비제한 파이프라이닝 모드)
- 리더는 미확인(In-flight) RPC의 개수를 전혀 제한하지 않고, 미전송 로그가 존재하는 한 즉시 낙관적으로 `next_index`를 전진시키며 RPC를 연속 전송합니다.
- 정상 상황에서는 높은 처리량을 보이지만:
  1. 팔로워가 일시 정지(Stall)되면 In-flight RPC 개수가 무제한 증가하여 버퍼 팽창(`peak_inflight_messages > 16`)이 발생합니다 (`UNBOUNDED_PIPELINING_BUFFER_BLOAT`).
  2. 팔로워의 로그와 충돌이 발생하면, 파이프라인에 이미 진입한 후속 In-flight RPC들이 연쇄적으로 거절당하며 재전송 폭풍(`cascading_rejection_storms > 0`)이 발생합니다 (`UNBOUNDED_PIPELINING_CASCADING_REJECTION_STORM`).
- 아무 문제 없이 완료된 경우 `UNBOUNDED_PIPELINING_STABLE`.

### 3. `PIPELINED_FLOW_CONTROL` (흐름 제어 기반 파이프라이닝 - etcd/raft 방식)
- 각 팔로워에 대해 이중 진행 상태(`StateProbe` vs `StateReplicate`)와 In-flight 슬라이딩 윈도우(`capacity = max_inflight`)를 유지합니다:
  - **`StateProbe` (탐색 모드)**: 초기 연결, 거절 복구 직후, 또는 하트비트 시 진입. 최대 허용 In-flight 개수는 **1개**(`allowed_limit = 1`)로 제한되어 정확한 로그 일치점(`match_index`)을 안전하게 탐색합니다. 응답이 성공하면 즉시 `StateReplicate`로 승격됩니다.
  - **`StateReplicate` (고속 복제 모드)**: 최대 `max_inflight`개(예: 8개)의 RPC를 동시에 파이프라이닝하여 네트워크 대역폭-지연 곱(BDP)을 완벽히 포화시킵니다.
- **슬라이딩 윈도우 회수 (`free_to`)**: 팔로워가 `match_index`로 성공 응답을 보내면, 해당 인덱스 이하를 담당하던 모든 In-flight 엔트리를 윈도우에서 즉시 방출하여 슬롯을 재확보합니다.
- **즉각적 강등 및 무효화 (Wipeout & Demote on Reject)**: 팔로워가 거절 응답을 반환하면:
  1. 즉시 진행 상태를 `StateProbe`로 강등합니다.
  2. **In-flight 윈도우를 즉시 전량 리셋(`inflights.reset()`)**하고 해당 팔로워의 기존 미확인 RPC ID들을 전부 무효화(`valid_rpc_ids.clear()`)합니다.
  3. 이후 도착하는 과거 파이프라인 잔여 응답들은 상태를 오염시키지 않고 즉시 무시/폐기됩니다.
  4. 단 1회의 탐색 RPC를 보내 정확한 `match_index`를 재협상하므로 **연쇄 거절 폭풍이 0건으로 완벽히 차단**됩니다.
- 평가 판정(Verdict): 100% 커밋, 연쇄 거절 0건, In-flight 상한 준수 시 `OPTIMAL_PIPELINED_FLOW_CONTROL_CONVERGENCE`.

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "cluster": {
    "nodes": ["node-1", "node-2", "node-3"],
    "leader_id": "node-1",
    "current_term": 2,
    "initial_match_index": {
      "node-2": 0,
      "node-3": 0
    },
    "network": {
      "default_rtt_ms": 10.0,
      "peer_rtt_ms": {
        "node-2": 10.0,
        "node-3": 10.0
      }
    }
  },
  "replication_config": {
    "mode": "PIPELINED_FLOW_CONTROL",
    "max_inflight": 8,
    "batch_size": 5
  },
  "workload": [
    {
      "type": "CLIENT_PROPOSE",
      "timestamp_ms": 0.0,
      "entries": [
        {"data": "cmd_1"},
        {"data": "cmd_2"}
      ]
    },
    {
      "type": "NETWORK_LATENCY_CHANGE",
      "timestamp_ms": 50.0,
      "peer_id": "node-2",
      "new_rtt_ms": 40.0
    },
    {
      "type": "FOLLOWER_STALL",
      "timestamp_ms": 20.0,
      "peer_id": "node-2",
      "duration_ms": 100.0
    },
    {
      "type": "INJECT_LOG_CONFLICT",
      "timestamp_ms": 0.0,
      "peer_id": "node-2",
      "diverge_at_index": 10,
      "diverge_term": 1
    }
  ]
}
```

### 필드 상세 명세:
- `cluster.nodes`: 클러스터에 참여하는 전체 노드 ID 리스트 ($N$개 노드, 과반수 쿼럼 $Q = \lfloor N/2 \rfloor + 1$).
- `cluster.leader_id`: 리더 노드 ID (기본값 `"node-1"`).
- `cluster.current_term`: 현재 리더의 임기 (정수).
- `cluster.initial_match_index`: 팔로워별 초기 일치 로그 인덱스 (생략 시 0).
- `cluster.network.default_rtt_ms`: 기본 네트워크 왕복 RTT (단방향 지연시간은 `rtt / 2.0`).
- `cluster.network.peer_rtt_ms`: 특정 팔로워의 개별 RTT 오버라이드.
- `replication_config.mode`: `"STOP_AND_WAIT"`, `"UNBOUNDED_PIPELINING"`, `"PIPELINED_FLOW_CONTROL"`.
- `replication_config.max_inflight`: 동시 미확인 RPC 슬라이딩 윈도우 용량 (정수).
- `replication_config.batch_size`: 단일 `AppendEntries` RPC에 포함되는 최대 로그 엔트리 수.
- `workload`: 시간순으로 발생하는 시뮬레이션 이벤트 목록:
  - `CLIENT_PROPOSE`: 리더에게 클라이언트 쓰기 제안 엔트리들이 도착함 (`timestamp_ms`, `entries`).
  - `NETWORK_LATENCY_CHANGE`: 특정 팔로워와의 네트워크 RTT 변경 (`timestamp_ms`, `peer_id`, `new_rtt_ms`).
  - `FOLLOWER_STALL`: 팔로워 노드가 GC pause나 디스크 fsync로 메시지 처리를 일시 중단함 (`timestamp_ms`, `peer_id`, `duration_ms`).
  - `INJECT_LOG_CONFLICT`: 특정 팔로워의 로그가 지정된 인덱스에서 다른 임기(`diverge_term`)의 충돌 로그로 분기됨 (`timestamp_ms`, `peer_id`, `diverge_at_index`, `diverge_term`).

---

## 출력 형식

표준 출력(Standard Output)으로 복제 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_PIPELINED_FLOW_CONTROL_CONVERGENCE",
  "replication_mode": "PIPELINED_FLOW_CONTROL",
  "metrics": {
    "total_proposals": 30,
    "committed_entries": 30,
    "commit_rate_pct": 100.0,
    "total_rpc_sent": 12,
    "total_rejections": 0,
    "cascading_rejection_storms": 0,
    "peak_inflight_messages": 5,
    "average_commit_latency_ms": 18.33,
    "max_commit_latency_ms": 20.0
  },
  "peers": {
    "node-2": {
      "final_match_index": 30,
      "final_next_index": 31,
      "final_state": "StateReplicate",
      "rpc_sent_count": 6,
      "rejections_count": 0,
      "cascading_rejections": 0,
      "max_inflight_reached": 5,
      "throttled_events_count": 1
    },
    "node-3": {
      "final_match_index": 30,
      "final_next_index": 31,
      "final_state": "StateReplicate",
      "rpc_sent_count": 6,
      "rejections_count": 0,
      "cascading_rejections": 0,
      "max_inflight_reached": 5,
      "throttled_events_count": 1
    }
  }
}
```

---

## 시뮬레이션 핵심 규칙 및 Raft 합의 법칙

1. **Raft 안전성 쿼럼 커밋 법칙 (Safety Section 5.4.2)**:
   - 리더는 클러스터 노드들(리더 포함)의 `match_index`를 내림차순 정렬했을 때 과반수 쿼럼 위치($Q$-번째 노드의 인덱스 $M$)를 찾습니다.
   - 단, $M$에 위치한 엔트리의 임기(`term`)가 현재 리더의 임기(`current_term`)와 일치해야만 커밋을 전진시킵니다.
2. **이산 사건 큐(Discrete-Event Priority Queue)**:
   - 모든 RPC와 응답은 `timestamp_ms + transit_delay`(`rtt / 2.0`) 시점에 정확하게 전달되어야 합니다.
   - 팔로워가 `FOLLOWER_STALL` 중인 경우, 메시지는 소멸되지 않고 팔로워의 스톨이 끝나는 시점(`stall_until_ms`)으로 지연 전달됩니다.
3. **팔로워 일치성 검증 및 충돌 탐지**:
   - 팔로워의 로그에서 `prev_log_index` 위치의 엔트리가 없거나 임기가 `prev_log_term`과 다르면 `success=False`로 거절합니다.
   - 거절 응답에는 팔로워가 보유한 첫 충돌 인덱스(`conflict_index`) 힌트가 포함됩니다.
4. **흐름 제어 슬라이딩 윈도우 관리**:
   - `PIPELINED_FLOW_CONTROL`에서 `StateProbe` 상태일 때는 동시 In-flight 개수를 1개로 제한합니다.
   - 성공 응답 도착 시 `free_to(match_index)`로 윈도우를 비우고 `StateReplicate`로 전환합니다.
   - 거절 응답 도착 시 즉시 `StateProbe`로 강등하고 윈도우를 전량 리셋(`reset()`)하여 이후 도착하는 이전 RPC 응답들을 폐기합니다.
