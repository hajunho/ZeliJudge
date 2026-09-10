# 분산 합의(Distributed Consensus) Raft Pre-Vote 프로토콜과 리더 리스(Leader Lease) 이론

## 1. 분산 시스템의 네트워크 비대칭 분할(Asymmetric Partitions)
실제 데이터센터에서는 케이블 접촉 불량, 스위치 버그, iptables 방화벽 오설정 등으로 인해 다음과 같은 **비대칭/부분 네트워크 분할**이 빈번하게 발생합니다:
- **격리된 노드(Isolated/Disrupted Node)**: 특정 노드 하나만 리더의 하트비트를 받지 못하지만, 다른 팔로워들에게는 패킷을 보낼 수 있는 상태.
- 원본 Raft 논문(In Search of an Understandable Consensus Algorithm, USENIX ATC '14)의 순수 알고리즘에서는 이 고립 노드가 주기적으로 임기를 올리며 선거를 시도합니다.
- 이 노드가 다시 리더와 연결되면, 자신이 쌓아 올린 비정상적인 고임기($Term=20$)로 인해 정상적으로 트랜잭션을 처리하던 리더가 즉시 강등(Demotion)되어 전체 클러스터가 멈칫하는 서비스 중단이 발생합니다.

---

## 2. Raft Pre-Vote 프로토콜의 작동 원리 (Ongaro 2014 §9.6)
Pre-Vote는 2단계 선거(Two-Phase Election)의 일종입니다:

```
[Follower] 
    | (Election Timeout)
    v
[PreCandidate] (Term stays unchanged!)
    |
    |-- Broadcast PreVote(Term + 1, CandidateID, LastLog) --> [Peers]
    |                                                             |
    |<-- Collect PreVote Responses (Requires Quorum) -------------+
    |
    +--> [Quorum Granted?]
             |-- YES --> Increment Term (+1), Become [Candidate], Broadcast real RequestVote!
             +-- NO  --> Revert/Stay Follower. (TERM IS PRESERVED!)
```

피어 노드가 Pre-Vote를 거절하는 핵심 조건은 **"자신이 알고 있는 리더가 최근 최소 선거 타임아웃 이내에 살아있었는가?"**입니다.
이 간단한 검사를 통해 고립된 노드의 임기 인플레이션(Term Inflation)을 100% 방지할 수 있습니다.

---

## 3. 리더 리스(Leader Lease)와 선형 일관성(Linearizable Reads)
Raft에서 읽기 요청을 처리하는 세 가지 방법:
1. **Raft 로그 기록 (Raft Log Entry)**: 읽기 요청도 Raft 로그로 기록하고 쿼럼 디스크에 fsync 커밋. 안전하지만 극도로 느림 ($100 \sim 1000$ ops/sec).
2. **Read Index (쿼럼 하트비트 왕복)**: 로그를 남기지 않지만, 현재 자신이 리더인지 확인하기 위해 쿼럼에 하트비트를 쏘아 ACK를 받아야 함 (1 RTT 지연).
3. **Leader Lease (로컬 리스 읽기)**:
   - 쿼럼 하트비트 ACK를 받은 시점부터 $T_{\text{lease}}$ 동안은 새로운 리더가 절대 선출될 수 없다는 불변식에 기반.
   - 네트워크 통신 없이 로컬 메모리에서 $O(1)$로 수십만 ops/sec 읽기 처리 가능.
   - 단, 서버 간 클록 왜곡(Clock Drift)을 방지하기 위해 보수적인 오차율 $\text{clock\_drift\_bound}$ (보통 $5\%$)를 차감해야 합니다.
