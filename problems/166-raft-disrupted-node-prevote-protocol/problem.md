# 네트워크 깜빡였을 뿐인데 왜 멀쩡한 리더가 쫓겨나고 클러스터가 멈춰요?!: Raft 분리 노드 재선출 스톰과 Pre-Vote 단계

## 1. 장애 현장: 새벽 3시, 멀쩡하던 etcd 클러스터의 의문의 리더 강제 폐위 참사

어느 날 새벽, 쿠버네티스(Kubernetes) 핵심 컨트롤 플레인인 5노드 `etcd` 분산 클러스터에서 원인 불명의 전면 서비스 장애가 발생했습니다.

모니터링 대시보드상으로 과반수 노드들의 CPU와 메모리는 20% 미만으로 극히 여유로웠고 디스크 I/O 역시 안정적이었습니다. 그런데 갑자기 수만 개의 마이크로서비스 파드 생성이 일제히 멈추고 `API Server: 503 Service Unavailable (Leader Lost)` 에러가 빗발치기 시작했습니다.

긴급 투입된 SRE 팀이 로그를 뜯어본 결과, 상상을 초월하는 기이한 현상이 기록되어 있었습니다:
```
[etcd-1 (LEADER, Term 1)] Serving 15,000 writes/sec normally...
[etcd-5 (FOLLOWER, Term 1)] Missed heartbeat due to top-of-rack switch packet drop!
[etcd-5] Election timer expired! Incrementing term: 1 -> 2, Becoming CANDIDATE.
[etcd-5] Broadcast RequestVote(term=2) to peers...
[etcd-1] Received RequestVote from etcd-5 with term=2 > currentTerm(1)!
[etcd-1] [CRITICAL] Standard Raft rule: Demoting from LEADER to FOLLOWER! Active leader lost!
[etcd-5] Inbound packets dropped, cannot receive vote responses. Election failed!
[Client Request] PUT /registry/pods/payment-service-xyz -> ERROR: NO_LEADER!
[etcd-5] Election timer expired again! Incrementing term: 2 -> 3...
[etcd-5] Re-election storm repeating! Cluster paralyzed for 45 seconds!
```

5대 노드 중 4대(`etcd-1, 2, 3, 4`)는 서로 완벽하게 연결되어 정상 트래픽을 처리하고 있었습니다. 단지 최하위 노드 `etcd-5`의 인바운드 스위치 포트에 일시적인 패킷 드랍이 발생해 하트비트를 받지 못했을 뿐입니다.
하지만 오리지널 Raft 명세의 **"더 높은 Term을 수신한 리더는 무조건 즉시 팔로워로 강등된다"**는 규칙 때문에, 고립된 낙후 노드가 던진 고임기 메시지 한 방에 멀쩡하던 합법적 리더가 쫓겨나고 클러스터 전체가 다운된 것입니다!

Diego Ongaro의 박사 학위 논문(Section 9.6)에서 제시된 **Pre-Vote 프로토콜(Pre-Vote Protocol)**을 시뮬레이션 엔진으로 구현하여, 이 비대칭 네트워크 파티션 재선출 스톰을 완벽하게 진압하고 100% 가용성을 보장하는 고신뢰 분산 합의 엔진을 완성하세요!

---

## 2. 요구 사항 및 시뮬레이션 규칙

입력으로 주어지는 클러스터 설정(`config`), 초기 상태(`initial_state`), 시간 순서대로 발생하는 이벤트(`commands`)를 순차적으로 처리하여 최종 클러스터 메트릭과 상태를 반환해야 합니다.

### 2.1 클러스터 구성 및 상태 정의
- 클러스터는 고유한 노드 ID 목록(`cluster_nodes`)으로 구성됩니다.
- 과반수 정족수(Majority Quorum)는 다음과 같이 계산됩니다:
  $$\text{majority\_count} = \lfloor N / 2 \rfloor + 1$$
- 각 노드는 다음 4가지 역할 중 하나를 가집니다:
  - `FOLLOWER`: 리더의 명령을 따르는 상태
  - `PRE_CANDIDATE`: (`enable_prevote=True`인 경우) 사전 투표 진행 중인 가상 후보 상태
  - `CANDIDATE`: 공식 본 선출을 진행 중인 정식 후보 상태
  - `LEADER`: 클러스터의 쓰기를 전담하고 하트비트를 발송하는 합법적 리더 상태

### 2.2 하트비트 (`HEARTBEAT`)
- 리더 노드는 주기적으로 연결 가능한 모든 피어에게 하트비트를 발송합니다.
- 하트비트를 수신한 피어 노드는:
  - 피어의 `current_term < leader_term`이면 `current_term = leader_term`, `role = "FOLLOWER"`로 갱신합니다.
  - 피어의 리더 ID(`leader_id`)를 해당 리더로 갱신하고, **마지막 하트비트 수신 시각**(`last_heartbeat_received`)과 선출 타이머 시각을 현재 시각으로 리셋합니다.
- 만약 리더가 보낸 메시지의 `term < peer_term`이라면, 리더의 임기가 뒤처진 것이므로 리더는 즉시 `FOLLOWER`로 강등(`leader_demotions += 1`)됩니다.

### 2.3 선출 타이머 만료 (`ELECTION_TIMEOUT`)
팔로워 또는 후보 노드의 선출 타이머가 만료되었을 때 동작은 `enable_prevote` 설정에 따라 완전히 달라집니다:

#### [A] 기본 Raft (`enable_prevote = False`)
1. 노드는 즉시 `current_term`을 1 증가시키고 `CANDIDATE` 상태로 진입합니다 (`elections_started += 1`).
2. 자신에게 투표하고(`voted_for = self`), 연결 가능한 모든 피어에게 `RequestVote(cand_term, cand_id, last_log_term, last_log_index)`를 전송합니다.
3. 피어가 `RequestVote`를 수신했을 때:
   - 만약 `cand_term > peer_term`이면:
     - 피어가 활성 `LEADER`였다면 즉시 폐위되어 `FOLLOWER`로 강등됩니다 (`leader_demotions += 1`).
     - 피어의 `current_term = cand_term`, `role = "FOLLOWER"`, `voted_for = None`으로 갱신됩니다.
   - 피어의 임기가 `cand_term`과 일치하고, 아직 아무에게도 투표하지 않았거나(`voted_for in [None, cand_id]`), 후보자의 로그가 피어의 로그보다 최신이거나 동등하다면(`is_log_up_to_date`) 투표를 승인합니다.
4. 후보자가 과반수의 투표를 획득하면 `LEADER`로 승격되고, 즉시 첫 하트비트를 전송하여 권한을 확립합니다.

#### [B] Pre-Vote 프로토콜 (`enable_prevote = True`)
1. 노드는 **실제 `current_term`을 올리지 않습니다!**
2. 노드는 `PRE_CANDIDATE` 상태로 진입하고 (`prevote_rounds_started += 1`), 가상 차기 임기 `target_term = current_term + 1`을 담아 피어들에게 `PreVote`를 요청합니다.
3. 피어가 `PreVote`를 수신했을 때 **2단계 게이트 검증**을 수행합니다:
   - **게이트 1: 리더 임대(Leader Lease) 검증**
     수신 피어 자신이 활성 `LEADER`이거나, 최근 `election_timeout` 이내에 활성 리더로부터 유효한 하트비트를 수신했다면:
     $$\text{time} - \text{last\_heartbeat\_received} < \text{election\_timeout}$$
     피어는 **Pre-Vote를 즉시 거부(REJECT)**합니다 (`prevotes_rejected_by_lease += 1`).
   - **게이트 2: 로그 완전성(Log Completeness) 검증**
     후보의 로그가 수신 피어의 로그보다 오래되었다면 Pre-Vote를 거부합니다 (`prevotes_rejected_by_log += 1`).
   - 두 게이트를 모두 통과한 경우에만 Pre-Vote를 승인합니다. **(주의: Pre-Vote 승인은 피어의 `current_term`이나 `voted_for`를 절대 바꾸지 않는 순수 자문용입니다.)**
4. 후보자가 **과반수의 Pre-Vote를 획득한 경우에만** 공식적으로 `current_term`을 1 증가시키고 `CANDIDATE`로 승격하여 정식 `RequestVote`를 수행합니다.
5. 과반수 획득에 실패하면 조용히 `FOLLOWER` 상태로 복귀하며, 클러스터의 기존 리더와 동료들은 아무런 방해도 받지 않습니다!

### 2.4 로그 완전성 규칙 (Log Completeness Rule)
후보의 마지막 로그가 `(cand_term, cand_index)`, 수신자의 마지막 로그가 `(recv_term, recv_index)`일 때:
- `cand_term != recv_term`이면: `cand_term > recv_term`이어야 최신입니다.
- `cand_term == recv_term`이면: `cand_index >= recv_index`이어야 최신입니다.

### 2.5 클라이언트 쓰기 (`CLIENT_WRITE`)
- 클라이언트가 데이터를 기록하려 할 때 활성 리더가 존재하지 않으면 쓰기는 즉시 실패(`client_writes_failed += 1`)합니다.
- 활성 리더가 존재하면 리더는 로컬 로그에 엔트리를 추가하고 연결 가능한 모든 피어에게 복제합니다.
- 리더를 포함하여 **과반수(Majority)** 이상의 노드가 복제를 완료(`ack`)하면 해당 엔트리가 커밋(`commit_index` 갱신)되며 성공(`client_writes_committed += 1`)합니다.
- 과반수 복제에 실패하면 쓰기는 실패(`client_writes_failed += 1`)합니다.

### 2.6 네트워크 제어 명령
- `BLOCK_EDGE`: `sender -> receiver` 단방향 네트워크 링크를 차단합니다.
- `UNBLOCK_EDGE`: `sender -> receiver` 단방향 네트워크 링크를 복구합니다.
- `ISOLATE_NODE`: 특정 노드의 모든 인바운드/아웃바운드 링크를 차단합니다.
- `RECONNECT_NODE`: 특정 노드의 모든 링크를 복구합니다.
- `ISOLATE_PARTITION`: 지정된 노드 그룹(`nodes`)과 나머지 노드들 간의 모든 양방향 링크를 차단합니다.
- `HEAL_ALL_PARTITIONS`: 클러스터의 모든 네트워크 차단을 해제하고 전면 연결을 복원합니다.

---

## 3. 입력 및 출력 형식

### 입력 형식 (JSON on stdin)
```json
{
  "config": {
    "cluster_nodes": ["node1", "node2", "node3", "node4", "node5"],
    "heartbeat_interval": 50,
    "election_timeout": 150,
    "enable_prevote": true
  },
  "initial_state": {
    "leader_id": "node1",
    "term": 1
  },
  "commands": [
    {"time": 0, "type": "HEARTBEAT", "leader_id": "node1"},
    {"time": 10, "type": "CLIENT_WRITE", "data": "tx_01"},
    {"time": 20, "type": "BLOCK_EDGE", "sender": "node1", "receiver": "node5"},
    {"time": 160, "type": "ELECTION_TIMEOUT", "node": "node5"}
  ]
}
```

### 출력 형식 (JSON on stdout)
```json
{
  "status": "SUCCESS",
  "metrics": {
    "leader_demotions": 0,
    "elections_started": 0,
    "prevote_rounds_started": 1,
    "prevotes_rejected_by_lease": 3,
    "prevotes_rejected_by_log": 0,
    "max_term": 1,
    "client_writes_committed": 1,
    "client_writes_failed": 0,
    "final_leader": "node1"
  },
  "node_states": {
    "node1": {
      "role": "LEADER",
      "term": 1,
      "commit_index": 1,
      "log_length": 1
    }
  },
  "timeline": [...]
}
```
