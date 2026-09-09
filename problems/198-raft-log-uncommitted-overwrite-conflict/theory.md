# Raft 분산 합의 이론: 비커밋 미동기화 로그 충돌과 Fast Backtracking 복구 매커니즘

## 1. Raft 로그 일치성 불변식 (Log Matching Property)
Raft(Diego Ongaro & John Ousterhout, 2014) 합의 프로토콜은 모든 분산 상태 머신 복제본(Replicated State Machine)이 동일한 순서로 동일한 연산을 실행하도록 보장하기 위해 두 가지 핵심 불변식을 수호합니다:

1. **동일 인덱스 & 동일 임기 불변식**:
   서로 다른 서버의 로그에 있는 두 항목이 동일한 인덱스 $i$와 동일한 임기 $t$를 가진다면, 이 두 항목은 동일한 커맨드를 저장한다.
2. **접두사 동일 불변식 (Prefix Identity)**:
   서로 다른 서버의 로그에 있는 두 항목이 동일한 인덱스 $i$와 동일한 임기 $t$를 가진다면, 인덱스 $1$부터 $i$까지의 모든 선행 로그 항목 또한 완전히 동일하다.

이 불변식은 리더가 팔로워에게 `AppendEntries RPC`를 전송할 때 수행하는 **일치성 검사(Consistency Check)**를 통해 귀납적으로 증명됩니다.

---

## 2. 리더 충돌과 비커밋 로그 파편화 (Raft 논문 Figure 7)
네트워크 지연, 파티션 분할, 이전 리더 노드의 비정상 종료(Crash)가 반복되면 팔로워 노드들은 정규 리더 로그와 심각하게 어긋난 비정상 상태에 빠질 수 있습니다.

```
Leader for term 8:  [1:1] [2:1] [3:1] [4:4] [5:4] [6:5] [7:5] [8:6] [9:6] [10:6]
Follower (a):       [1:1] [2:1] [3:1] [4:4] [5:4] [6:5] [7:5] [8:6] [9:6] (엔트리 누락)
Follower (b):       [1:1] [2:1] [3:1] [4:4] (심각한 엔트리 누락)
Follower (c):       [1:1] [2:1] [3:1] [4:4] [5:4] [6:5] [7:5] [8:6] [9:6] [10:6] [11:6] (미커밋 잉여)
Follower (d):       [1:1] [2:1] [3:1] [4:4] [5:4] [6:5] [7:5] [8:6] [9:6] [10:6] [11:7] [12:7] (미커밋 임기 7)
Follower (e):       [1:1] [2:1] [3:1] [4:4] [5:4] [6:4] [7:4] (임기 4 충돌 파편)
Follower (f):       [1:1] [2:1] [3:1] [4:2] [5:2] [6:2] [7:3] [8:3] [9:3] [10:3] [11:3] (다중 임기 충돌)
```

- **(a), (b)**: 일시적 다운으로 인해 정상 커밋된 엔트리를 아직 받지 못함.
- **(c)**: 이전 임기 6의 리더였던 노드가 엔트리 11을 로컬 로그에 썼으나 과반수 복제 전 크래시함.
- **(d)**: 임기 7의 리더가 엔트리 11, 12를 쓰고 크래시함.
- **(e)**: 임기 4에서 일부 엔트리를 쓴 후 이후 임기 5, 6을 전혀 수신하지 못함.
- **(f)**: 임기 2, 3에서 분할 상태로 쓰기를 받았으나 전혀 커밋되지 못한 채 파편화됨.

새 리더는 팔로워의 로그를 강제로 수정할 권한을 가집니다. 리더는 팔로워와 일치하는 가장 최근의 로그 인덱스를 찾아낸 후, **그 지점 이후의 모든 팔로워 로그를 과감히 Truncate(삭제)하고 자신의 로그로 덮어씁니다.**

---

## 3. 역추적 알고리즘: Naive Decrement vs Fast Backtracking

### 3.1 Naive Decrement 방식
- 리더는 팔로워마다 `nextIndex = leader.lastLogIndex + 1`로 초기화합니다.
- `AppendEntries(prevLogIndex = nextIndex - 1, prevLogTerm)`를 전송합니다.
- 팔로워가 거절(`success = false`)할 때마다 `nextIndex`를 단순히 1씩 감소시킵니다 (`nextIndex--`).
- **문제점**: 수천 개의 비커밋 로그가 상충하는 경우, 일치점을 찾기 위해 수천 번의 RPC 왕복(RTT)이 소요됩니다. 이는 고속 복구가 생명인 프로덕션 데이터베이스에서 용납될 수 없는 장애 지연을 유발합니다.

### 3.2 Fast Backtracking 최적화 (Raft Section 5.3)
팔로워가 일치성 검사에 실패하여 거절할 때, 단순 거절이 아니라 **충돌 힌트(`conflictTerm`, `conflictIndex`)**를 반환합니다:
1. **Case 1: 팔로워 로그가 너무 짧은 경우 (`prevLogIndex > follower.lastLogIndex`)**:
   - 팔로워는 `conflictTerm = None`, `conflictIndex = follower.lastLogIndex + 1`을 반환합니다.
   - 리더는 `nextIndex = conflictIndex`로 즉시 점프하여 빈 공간을 건너뜁니다.
2. **Case 2: 임기 불일치 발생 (`follower.log[prevLogIndex].term != prevLogTerm`)**:
   - 팔로워는 자신의 불일치 임기 `conflictTerm`과 그 임기가 팔로워 로그에서 **최초로 등장한 인덱스 `conflictIndex`**를 반환합니다.
   - **리더의 처리**:
     - 만약 리더의 로그에도 `conflictTerm`을 가진 엔트리가 존재한다면: 리더는 자신의 로그에서 해당 `conflictTerm`의 마지막 엔트리 인덱스를 찾고, `nextIndex = last_index_with_term + 1`로 설정합니다.
     - 만약 리더의 로그에 `conflictTerm`이 전혀 존재하지 않는다면: 팔로워의 해당 임기는 통째로 폐기 대상이므로 `nextIndex = conflictIndex`로 설정하여 **해당 임기 전체를 단 1회의 RTT로 건너뜁니다!**

---

## 4. 커밋 안전성 규칙 (Figure 8 Safety Rule)
Raft 논문 5.4.2절("이전 임기의 로그 항목 커밋")은 초보 엔지니어가 가장 많이 오해하는 치명적인 합의 규칙을 다룹니다:

> **"리더는 이전 임기(Previous Term)의 로그 항목을 단순히 사본 개수를 세는 것만으로 커밋할 수 없다."**

- 만약 리더가 과거 임기의 엔트리가 과반수 노드에 복제되었다고 해서 독자적으로 `commitIndex`를 전진시킨다면, 구 임기 리더가 뒤늦게 살아나서 선출될 경우 이미 커밋되었다고 믿었던 데이터가 덮어씌워지는 대참사가 발생할 수 있습니다.
- 따라서 리더는 오직 **자신의 현재 임기(`currentTerm`)에서 생성된 로그 항목이 과반수 쿼럼에 복제되었을 때만** `commitIndex`를 전진시킬 수 있습니다.
- 현재 임기의 로그 항목이 커밋되는 순간, Raft의 **접두사 동일 불변식(Prefix Identity)**에 의해 그 이전에 적재된 과거 임기의 모든 선행 로그 항목들도 간접적으로 안전하게 영구 커밋됩니다.

---

## 5. 엔터프라이즈 실무 아키텍처 비교표

| 합의 엔진 | 로그 역추적 전략 | 비커밋 Truncation 처리 | 리더 임기 무효화 보호 |
| :--- | :--- | :--- | :--- |
| **etcd (Raft Core)** | Fast Backtracking (Term Search) | WAL Segment Truncation at Uncommitted Boundary | Pre-Vote Protocol & Term Guard |
| **TiKV (Raft Engine)** | AppendEntries Fast Reject Hint | Storage Engine SST Truncation & RaftLog Purge | ReadIndex / Lease Read Linearizability |
| **HashiCorp Consul** | Fast Log Index Backtrack | BoltDB / In-Memory Log Truncate | Raft State Machine Snapshot Sync |
| **SOFA-JRaft** | Segment-based Fast Scan | Pipeline RPC Batch Truncate | Disruptor RingBuffer Lock-Free Replication |
