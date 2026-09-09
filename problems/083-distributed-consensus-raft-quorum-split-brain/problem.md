# 083 - 서버를 4대로 늘렸는데 왜 2대로 쪼개지자마자 서비스가 터져요?!: 분산 합의(Raft)와 쿼럼(Quorum) 과반수 & 스플릿 브레인(Split-Brain) 방어

## 1. 현실 비유 & 배경 스토리

승무원 5명이 탑승한 대형 유람선이 있습니다. 🚢🌊  
폭풍우가 몰아치며 배의 통신선이 끊겨 선미 구역(노드 1, 2, 3)과 선수 구역(노드 4, 5)이 완전히 단절되었습니다.

만약 두 구역에서 통신이 두절되었다고 "내가 선장이다!" 하고 각각 선장을 뽑는다면 어떻게 될까요?
- 선미의 선장 1: "암초를 피해 **우현(오른쪽)**으로 전속력 회항하라!"
- 선수의 선장 2: "항로를 따라 **좌현(왼쪽)**으로 전속력 회항하라!"

배가 반으로 찢어지며 승객 전원이 수장되고 맙니다.

```text
[네트워크 파티션으로 쪼개진 5노드 클러스터]
  ┌──────────────┐                  ┌──────────────┐
  │ 노드 1, 2, 3 │  (네트워크 단절)  │   노드 4, 5  │
  │   (3대 그룹)  │ <=== X X X ===>  │  (2대 그룹)   │
  └──────────────┘                  └──────────────┘
         │                                 │
   과반수(3표) 확보!                 과반수(3표) 미달!
   합법적 리더 선출 및 정상 쓰기      ★ 쓰기 거절 (스플릿 브레인 방어)
```

이것이 바로 Kubernetes(etcd), ZooKeeper, Kafka(KRaft), TiDB 등 분산 데이터베이스에서 가장 두려워하는 **스플릿 브레인 (Split-Brain, 분할 뇌)** 참사입니다.

네트워크 장애(Network Partition)로 클러스터가 두 동강 났을 때, 양쪽 서브넷이 모두 리더를 세우고 클라이언트의 쓰기 요청을 제각각 수락한다면 동일한 키에 서로 다른 데이터가 덮어써져 데이터베이스가 영구적으로 파괴됩니다.

이를 방지하기 위해 분산 합의 알고리즘(Raft, Paxos)은 **과반수 쿼럼(Majority Quorum, $Q = \lfloor N/2 \rfloor + 1$)** 원칙을 강제합니다:
- 클러스터 전체 노드 수가 5대라면, 쿼럼은 **3표**입니다.
- 3대 구역은 과반수를 만족하므로 합법적으로 새 리더를 선출하고 쓰기를 커밋할 수 있습니다.
- 2대 구역은 쿼럼에 미달하므로, 기존 리더가 있더라도 **쓰기 요청을 즉시 거절(`REJECTED_NO_QUORUM`)**하여 데이터 불일치와 스플릿 브레인을 원천 차단합니다!

"서버 4대로 하면 2대씩 짝이 맞아서 더 안정적이지 않나요?"  
아닙니다! 4대 노드에서 2대:2대로 쪼개지면 양쪽 모두 과반수(3표)를 확보하지 못해 전사 서비스가 100% 마비됩니다.  
이것이 바로 빅테크 기업들이 etcd나 ZooKeeper 노드를 **반드시 3대, 5대 같은 홀수로 구성하는 이유**입니다.

당신은 Raft 쿼럼 시뮬레이터를 구축하여, 네트워크 분할 및 복구 환경에서 과반수 쿼럼 검증과 스플릿 브레인 방어 로직을 구현해야 합니다!

---

## 2. 분산 합의 상세 알고리즘 사양

클러스터는 $N$대의 노드로 구성되며, 노드 번호는 $1, 2, \dots, N$입니다.  
과반수 쿼럼(Majority Quorum) 기준:
$$Q = \left\lfloor \frac{N}{2} \right\rfloor + 1$$

초기 상태:
- 모든 노드가 단일 네트워크에 속해 있습니다.
- $1$번 노드가 초기 리더(`LEADER`)이며, 임기(`term`)는 $1$입니다.
- 나머지 노드들은 팔로워(`FOLLOWER`)입니다.

### 1) 쓰기 요청 (`WRITE <node_id> <key> <value>`)
1. `node_id`가 현재 리더가 아니라면:
   - `REJECTED_NOT_LEADER CURRENT_LEADER=<leader_id>` 반환 (쓰기 불가).
2. `node_id`가 리더라면, 자신이 속한 현재 파티션 그룹의 노드 수(`group_size`)를 검사합니다:
   - 만약 `group_size < Q` (과반수 상실, 소수파 구역에 고립됨):
     - **스플릿 브레인 방어 발동!**
     - `REJECTED_NO_QUORUM (MEMBERS: <group_size>/<Q>)` 반환 (쓰기 차단).
   - 만약 `group_size >= Q` (과반수 쿼럼 만족):
     - 해당 파티션 그룹 내의 모든 노드에 로그를 복제하고 즉시 커밋합니다:
       `node.store[key] = value`
     - `COMMITTED KEY=<key> VALUE=<value> TERM=<term> REPLICAS=<group_size>` 반환.

### 2) 리더 선출 (`ELECT <node_id>`)
1. `node_id`가 속한 파티션 그룹의 노드 수(`group_size`)를 검사합니다.
2. 만약 `group_size < Q`:
   - 과반수 득표 실패: `ELECTION_FAILED NODE=<node_id> (VOTES: <group_size>/<Q>)` 반환.
3. 만약 `group_size >= Q`:
   - 클러스터 임기(`current_term`)가 1 증가합니다.
   - 기존 리더는 팔로워로 강등되고, `node_id`가 새 리더(`LEADER`)로 선출됩니다.
   - 해당 파티션 그룹 내의 모든 노드는 새로운 `term`으로 갱신됩니다.
   - `ELECTED NODE=<node_id> TERM=<term> (VOTES: <group_size>/<Q>)` 반환.

### 3) 네트워크 파티션 및 복구 (`PARTITION`, `HEAL`)
- `PARTITION <group1> <group2> ...`:
  - 노드들을 여러 개의 격리된 파티션으로 분할합니다 (각 그룹은 콤마 구분).
  - 같은 그룹에 속한 노드끼리만 통신 및 쿼럼 계산이 가능합니다.
- `HEAL`:
  - 모든 파티션이 단일 네트워크 `[1, 2, ..., N]`으로 복구됩니다.
  - 현재 리더가 가진 최신 커밋 데이터(`store`)와 `term`이 모든 노드로 동기화(Reconciliation)됩니다.

---

## 3. 입력 명령 프로토콜

표준 입력(stdin)으로 다음 명령어들이 한 줄씩 주어집니다:

1. `INIT <num_nodes>`
   - $N$개의 노드로 클러스터를 초기화합니다 ($3 \le N \le 9$).
   - 출력: `INITIALIZED NODES=<N> QUORUM=<Q> LEADER=1 TERM=1`

2. `WRITE <node_id> <key> <value>`
   - `node_id`에 키-값 쓰기를 요청합니다.
   - 출력:
     - 커밋 성공 시: `COMMITTED KEY=<key> VALUE=<value> TERM=<term> REPLICAS=<group_size>`
     - 리더가 아닐 시: `REJECTED_NOT_LEADER CURRENT_LEADER=<leader_id>`
     - 과반수 미달 시: `REJECTED_NO_QUORUM (MEMBERS: <group_size>/<Q>)`

3. `ELECT <node_id>`
   - `node_id`의 리더 선출을 시도합니다.
   - 출력:
     - 성공 시: `ELECTED NODE=<node_id> TERM=<term> (VOTES: <group_size>/<Q>)`
     - 실패 시: `ELECTION_FAILED NODE=<node_id> (VOTES: <group_size>/<Q>)`

4. `PARTITION <group1> <group2> ...`
   - 네트워크 파티션을 생성합니다 (예: `PARTITION 1,2 3,4,5`).
   - 출력: `PARTITIONED GROUPS=[[1, 2], [3, 4, 5]]` (정렬된 리스트)

5. `HEAL`
   - 네트워크 파티션을 해소하고 단일 원천으로 동기화합니다.
   - 출력: `NETWORK_HEALED LEADER=<leader_id> TERM=<term>`

6. `READ <node_id> <key>`
   - 특정 노드의 커밋된 키 값을 조회합니다.
   - 출력: `READ NODE=<node_id> KEY=<key> VALUE=<value>` (없으면 `VALUE=NONE`)

7. `STATUS`
   - 클러스터 상태를 출력합니다:
     ```
     TOTAL_NODES: <N>
     QUORUM: <Q>
     TERM: <term>
     LEADER: <leader_id>
     PARTITIONS: [[...], [...]]
     NODE_STATES:
       NODE 1: ROLE=LEADER TERM=1 COMMITTED_KEYS=2
       NODE 2: ROLE=FOLLOWER TERM=1 COMMITTED_KEYS=2
       ...
     ```

---

## 4. 제약 조건

- $3 \le \text{num\_nodes} \le 9$
- 총 명령어 수 $\le 3,000$
- `key`와 `value`는 공백 없는 영문자/숫자/언더스코어 문자열

---

## 5. 입출력 예시

### 예시 입력
```
INIT 5
WRITE 1 user_101 alice
READ 2 user_101
PARTITION 1,2 3,4,5
WRITE 1 user_102 bob
ELECT 3
WRITE 3 user_102 charlie
READ 4 user_102
READ 1 user_102
HEAL
READ 1 user_102
STATUS
```

### 예시 출력
```
INITIALIZED NODES=5 QUORUM=3 LEADER=1 TERM=1
COMMITTED KEY=user_101 VALUE=alice TERM=1 REPLICAS=5
READ NODE=2 KEY=user_101 VALUE=alice
PARTITIONED GROUPS=[[1, 2], [3, 4, 5]]
REJECTED_NO_QUORUM (MEMBERS: 2/3)
ELECTED NODE=3 TERM=2 (VOTES: 3/3)
COMMITTED KEY=user_102 VALUE=charlie TERM=2 REPLICAS=3
READ NODE=4 KEY=user_102 VALUE=charlie
READ NODE=1 KEY=user_102 VALUE=NONE
NETWORK_HEALED LEADER=3 TERM=2
READ NODE=1 KEY=user_102 VALUE=charlie
TOTAL_NODES: 5
QUORUM: 3
TERM: 2
LEADER: 3
PARTITIONS: [[1, 2, 3, 4, 5]]
NODE_STATES:
  NODE 1: ROLE=FOLLOWER TERM=2 COMMITTED_KEYS=2
  NODE 2: ROLE=FOLLOWER TERM=2 COMMITTED_KEYS=2
  NODE 3: ROLE=LEADER TERM=2 COMMITTED_KEYS=2
  NODE 4: ROLE=FOLLOWER TERM=2 COMMITTED_KEYS=2
  NODE 5: ROLE=FOLLOWER TERM=2 COMMITTED_KEYS=2
```

### 힌트 & 분석
1. `PARTITION 1,2 3,4,5` 발생 후:
   - 노드 1은 여전히 리더 지위를 유지하고 있지만, 자신이 속한 그룹(1, 2)의 크기가 2로 쿼럼(3표)에 미달합니다.
   - 따라서 `WRITE 1 user_102 bob` 요청 시 **즉시 `REJECTED_NO_QUORUM`으로 거절하여 데이터 오염을 방어**합니다!
2. 다수파 구역(`3, 4, 5`):
   - 크기가 3으로 쿼럼(3표)을 충족하므로 `ELECT 3`을 통해 합법적으로 노드 3을 새 리더로 선출합니다 (`TERM=2`).
   - 새 리더 노드 3은 `user_102 charlie`를 정상 커밋합니다.
3. `HEAL` 복구 후:
   - 다수파 리더(노드 3)의 최신 데이터가 고립되었던 노드 1, 2로 복제되어, 전체 노드가 일관된 단일 상태(`user_102 = charlie`)로 수렴합니다!
