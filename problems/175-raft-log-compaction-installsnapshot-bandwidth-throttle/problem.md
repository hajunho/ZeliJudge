# 멀쩡하던 etcd 클러스터가 느린 노드 하나 복구하다 왜 다 같이 죽어요?!: Raft 로그 컴팩션(Log Compaction), 느린 팔로워의 InstallSnapshot 폭풍과 스냅샷 스트리밍 대역폭 스로틀링(Raft Log Truncation vs InstallSnapshot Streaming Bandwidth Throttling & Trailing Log Margin)

## 1. 장애 현장: 일시 분리 노드 1대 재접속 순간 터진 etcd 전면 마비 참사

대규모 쿠버네티스(Kubernetes) 엔터프라이즈 클러스터의 핵심 분산 키-값 저장소인 etcd(3노드 Raft 합의 클러스터)에서 기이하고 파멸적인 장애가 발생했습니다.

평소 초당 수천 건의 파드 스케줄링과 상태 갱신을 안정적으로 처리하던 중, 3번 노드(`node-3`)에서 약 30초 동안 짧은 네트워크 깜빡임(또는 긴 Stop-The-World GC 정지)이 발생했습니다.
잠시 후 3번 노드의 네트워크가 정상 복구되어 클러스터에 다시 접속한 바로 그 순간, **정상적으로 서비스를 제공하던 리더 노드(`node-1`)가 갑자기 쫓겨나고, 멀쩡하던 2번 노드(`node-2`)마저 선출 타임아웃(Election Timeout)을 연달아 터뜨리며 클러스터 전체가 45초간 완전히 마비**되었습니다:

```
[Leader: node-1]
      |
      | 1. node-3 격리 중 100건 이상의 신규 로그 커밋 & 상태 머신 적용
      | 2. 디스크 용량 한계로 주기적 로그 컴팩션(Log Compaction) 실행!
      |    -> 1번부터 99번까지의 과거 WAL 로그를 디스크에서 완전 삭제(Truncate)!
      |
      | 3. node-3 재접속! "저 11번 로그부터 주세요!" (next_index = 11)
      | 4. Leader: "11번 로그는 이미 삭제됐다! 통째로 스냅샷(InstallSnapshot) 받아라!"
      v
[InstallSnapshot 폭풍 (Unconstrained Snapshot Streaming)]
      | 5. 수 기가바이트 스냅샷 청크를 네트워크 대역폭 제한 없이 100% 쏟아냄!
      | 6. 리더의 네트워크 인터페이스(NIC) 송신 대역폭 포화!
      | 7. 정상 노드(node-2)로 보내는 하트비트(AppendEntries Heartbeat) 패킷 드랍!
      v
[node-2: Election Timeout Exceeded!]
      - node-2: "리더로부터 하트비트가 안 온다! 내가 새 리더가 되겠다!" (RequestVote 폭탄)
      - 정상 리더 폐위 및 클러스터 스플릿 브레인/재선출 스톰 발발!
      - Kubernetes API Server 503 Service Unavailable 및 배포 전면 중단!
```

사후 분석 결과, 문제는 **Raft 로그 컴팩션(Log Compaction) 후 느린 팔로워의 InstallSnapshot 전송 시 대역폭 제어가 없었던 점**과 **너무 공격적인 로그 삭제(0 Trailing Log Margin)**였습니다.

1. **대역폭 스로틀링 부재**:
   수 기가바이트의 스냅샷을 최대 속도로 전송하느라 합의 알고리즘의 생명줄인 **하트비트(Heartbeat) 통신 채널이 질식(Starvation)**했습니다.
2. **잔여 로그 마진 부재**:
   리더가 커밋된 로그를 단 1개도 남기지 않고 즉시 잘라내어(`compact_index = applied_index`), 수 초간의 일시적 지연만으로도 무조건 값비싼 스냅샷 전송이 강제되었습니다.

이를 해결하기 위해 최신 etcd 및 TiKV, CockroachDB는:
- **스냅샷 스트리밍 대역폭 제한기 (`snapshot_throttle_bytes_per_tick`)**
- **안전 마진을 둔 로그 보존 기법 (`trailing_log_margin`)**

을 도입하고 있습니다. 당신은 Raft 합의 엔진의 로그 컴팩션 및 스냅샷 복구 시뮬레이터를 구현해야 합니다.

---

## 2. 요구 사항 및 알고리즘 명세

입력으로 주어지는 시스템 파라미터(`system`)와 틱(초 단위, `workload`)별 클라이언트 제안(`proposals`) 및 네트워크 상태 변화(`network_events`)를 시뮬레이션하여 클러스터 상태와 메트릭을 도출해야 합니다.

### 2.1 시스템 설정 파라미터
`system` 객체로부터 다음 설정을 파싱합니다:
- `nodes`: 클러스터 노드 ID 목록 (기본값: `["node-1", "node-2", "node-3"]`, 첫 번째 노드가 초기 리더)
- `trailing_log_margin`: 로그 컴팩션 시 `applied_index` 뒤에 유지할 잔여 안전 로그 개수 (기본값: 0)
- `compaction_threshold_logs`: 리더의 로그 개수가 이 임계치에 도달하면 컴팩션 실행 (기본값: 100)
- `snapshot_throttle_bytes_per_tick`: 틱당 스냅샷 최대 전송 바이트 한도 (0이면 무제한, 기본값: 0)
- `heartbeat_loss_threshold_bytes`: 틱당 리더 송신 트래픽이 이 값을 초과하면 하트비트 유실 발생 (기본값: 20000)
- `election_timeout_ticks`: 연속 하트비트 누락 허용 한도 (기본값: 3)
- `bytes_per_log_entry`: 로그 1건당 크기 (기본값: 100 Bytes)
- `bytes_per_snapshot_entry`: 스냅샷 상태 엔트리 1건당 크기 (기본값: 200 Bytes)

---

### 2.2 틱(Tick)별 Raft 시뮬레이션 6단계 라이프사이클

리더가 폐위(`leader_dethroned == True`)되지 않은 동안, 매 틱마다 다음 순서로 실행합니다:

#### 1단계: 네트워크 파티션/재접속 이벤트 반영
- `network_events`: `{node_id: "PARTITION" | "RECONNECT"}`
- `"PARTITION"`: 해당 팔로워를 격리 상태로 변경 (`partitioned = True, status = "PARTITIONED"`).
- `"RECONNECT"`: 격리 해제 (`partitioned = False, missed_heartbeats = 0, status = "RECONNECTED"`).

#### 2단계: 리더의 클라이언트 제안 수신 및 WAL 추가
- `proposals`의 각 항목에 대해 고유한 인덱스(`idx = first_log_index + len(leader_logs)`)를 부여하고 리더의 로그에 추가합니다:
  $$\text{total\_proposals} \mathrel{+}= 1, \quad \text{leader\_logs.append}(\{\text{index}, \text{term}, \text{data}\})$$

#### 3단계: 팔로워 복제 및 송신 트래픽(`tick_egress_bytes`) 산출
격리되지 않은 모든 팔로워에 대해 순차적으로 복제 상태를 평가합니다:
1. **스냅샷 진행 중인 경우 (`snapshot_in_progress == True`)**:
   - 잔여 스냅샷 바이트(`remaining = snapshot_total_bytes - snapshot_bytes_transferred`) 계산.
   - 틱당 전송 바이트 결정:
     - `snapshot_throttle_bytes > 0`인 경우: $\text{send} = \min(\text{remaining}, \; \text{snapshot\_throttle\_bytes})$
     - 그 외 (무제한): $\text{send} = \text{remaining}$
   - $\text{snapshot\_bytes\_transferred} \mathrel{+}= \text{send}, \quad \text{tick\_egress\_bytes} \mathrel{+}= \text{send}$
   - 완료 검사: $\text{transferred} \ge \text{total}$이면 스냅샷 적용 완료:
     - `snapshot_in_progress = False, status = "SNAPSHOT_APPLIED"`
     - 팔로워의 `match_index = snapshot_target_index, next_index = snapshot_target_index + 1`
     - $\text{snapshots\_transmitted} \mathrel{+}= 1$
   - 미완료 시 `status = "SNAPSHOT_STREAMING"`
2. **스냅샷 신규 시작 필요 (`next_index < leader.first_log_index`)**:
   - 팔로워가 요구하는 인덱스의 로그가 리더의 컴팩션으로 이미 삭제된 상태입니다!
   - $\text{total\_snap\_bytes} = \text{leader.snapshot\_index} \times \text{bytes\_per\_snapshot\_entry}$
   - 스냅샷 전송을 초기화하고 당해 틱에 전송 가능한 분량(`send`)만큼 즉시 송신 및 트래픽 가산.
3. **델타 로그 복제 (일반 `AppendEntries`)**:
   - 리더의 로그 중 팔로워의 `next_index` 이상인 엔트리들을 추출하여 전송합니다:
     $$\text{send\_bytes} = \text{len(entries)} \times \text{bytes\_per\_log\_entry} + 50 \text{ (RPC Header)}$$
     $$\text{tick\_egress\_bytes} \mathrel{+}= \text{send\_bytes}$$
   - 엔트리가 있다면 팔로워의 `match_index`를 마지막 엔트리의 인덱스로 갱신하고 `status = "DELTA_REPLICATING"`, 없으면 `status = "IN_SYNC"`.

#### 4단계: 과반수 쿼럼(Quorum) 기반 리더 커밋 갱신
- 활성 노드들의 `match_index` 목록을 내림차순 정렬하여 과반수 위치($\lfloor N/2 \rfloor$)의 인덱스로 리더의 `commit_index`를 갱신합니다.
- $\text{total\_committed} = \text{leader\_commit\_index}$

#### 5단계: 리더의 로그 컴팩션 (Log Compaction)
- 리더의 로그 개수(`len(leader_logs)`)가 `compaction_threshold_logs` 이상이면 컴팩션을 수행합니다:
  $$\text{target\_compact\_index} = \text{leader\_applied\_index} - \text{trailing\_log\_margin}$$
- $\text{target\_compact\_index} > \text{first\_log\_index}$인 경우:
  - $\text{target\_compact\_index}$ 미만의 로그를 리더의 WAL에서 완전 제거(Truncate)합니다.
  - `first_log_index = target_compact_index, snapshot_index = target_compact_index - 1`
  - $\text{compactions\_executed} \mathrel{+}= 1$

#### 6단계: 대역폭 포화 및 하트비트 유실 평가
- 만약 $\text{tick\_egress\_bytes} > \text{heartbeat\_loss\_threshold\_bytes}$라면:
  - 송신 대역폭 포화로 하트비트 패킷이 유실됩니다! ($\text{heartbeats\_lost} \mathrel{+}= 1, \text{heartbeat\_dropped} = \text{True}$)
  - 격리되지 않은 모든 팔로워의 `missed_heartbeats += 1`.
  - 만약 어떤 팔로워의 $\text{missed\_heartbeats} \ge \text{election\_timeout\_ticks}$라면:
    - 팔로워가 선출 타임아웃을 발동하여 리더를 강제 폐위시킵니다:
      $$\text{leader\_dethroned} = \text{True}, \quad \text{election\_events} \mathrel{+}= 1$$
- 유실이 없다면 연결된 팔로워들의 `missed_heartbeats`를 0으로 리셋합니다.

---

### 2.3 최종 판정 규칙 (`verdict`)

1. 리더가 폐위된 경우 $\to$ `"LEADER_DETHRONED_CASCADING_ELECTION"` (전체 상태: `FAILED`)
2. 스냅샷 전송이 발생한 경우:
   - `snapshot_throttle_bytes > 0` $\to$ `"SNAPSHOT_BANDWIDTH_THROTTLED_STABLE"`
   - 그 외 $\to$ `"SNAPSHOT_UNCONSTRAINED_RECOVERED"`
3. 파티션이 발생했으나 스냅샷 없이 마진 내에서 복구된 경우 $\to$ `"TRAILING_MARGIN_DELTA_CATCHUP"`
4. 파티션 없이 정상 유지된 경우 $\to$ `"STEADY_STATE_REPLICATION"`

---

## 3. 입출력 포맷

### 입력 형식 (JSON on stdin)
```json
{
  "system": {
    "nodes": ["node-1", "node-2", "node-3"],
    "trailing_log_margin": 10,
    "compaction_threshold_logs": 20,
    "snapshot_throttle_bytes_per_tick": 5000,
    "heartbeat_loss_threshold_bytes": 15000,
    "election_timeout_ticks": 3
  },
  "workload": [
    {"tick": 1, "proposals": ["cmd_1", "cmd_2"], "network_events": {}},
    {"tick": 2, "proposals": ["cmd_3"], "network_events": {"node-3": "PARTITION"}},
    {"tick": 3, "proposals": ["cmd_4"], "network_events": {"node-3": "RECONNECT"}}
  ]
}
```

### 출력 형식 (JSON on stdout)
```json
{
  "status": "SUCCESS",
  "summary": {
    "nodes": ["node-1", "node-2", "node-3"],
    "trailing_log_margin": 10,
    "compaction_threshold_logs": 20,
    "snapshot_throttle_bytes_per_tick": 5000,
    "heartbeat_loss_threshold_bytes": 15000
  },
  "metrics": {
    "total_proposals": 4,
    "total_committed": 4,
    "compactions_executed": 0,
    "snapshots_transmitted": 0,
    "heartbeats_lost": 0,
    "peak_egress_bytes_per_tick": 450,
    "election_events": 0,
    "verdict": "TRAILING_MARGIN_DELTA_CATCHUP"
  },
  "sample_timeline": [...]
}
```
