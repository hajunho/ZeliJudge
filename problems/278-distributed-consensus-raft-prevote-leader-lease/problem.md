# 문제 #278: 네트워크 파티션 격리 노드가 복귀할 때 멀쩡한 리더가 왜 쫓겨날까요?!: 분산 합의(Distributed Consensus) Raft Pre-Vote 프로토콜 및 클록 드리프트 경계(Clock Drift Bound) 리더 리스(Leader Lease) 엔진

## 1. 개요 (Story & Context)
클라우드 인프라(Kubernetes의 etcd, TiKV, CockroachDB, HashiCorp Consul)의 심장부에는 고가용성과 일관성을 책임지는 **Raft 분산 합의 알고리즘(Distributed Consensus)**이 작동하고 있습니다.

그러나 2014년 Diego Ongaro와 John Ousterhout의 원본 Raft 논문 규격 그대로 구현된 순수(Naive) Raft 클러스터를 운영하다 보면, 현업에서 매우 치명적인 **‘격리 노드 복귀에 의한 리더 퇴출 참사(Disrupted Node Leader Demotion Problem)’**를 겪게 됩니다:
- 5개 노드로 구성된 클러스터에서 노드 5(N5)가 네트워크 스위치 장애로 인해 나머지 4개 노드와 일시적으로 고립되었다고 가정합시다.
- N5는 리더로부터 주기적인 하트비트(`AppendEntries`)를 받지 못하므로 선거 타이머(Election Timeout)가 계속해서 만료됩니다.
- 순수 Raft 규격에 따라 N5는 타이머가 터질 때마다 자신의 임기(Term)를 1씩 올립니다 ($Term: 1 \to 2 \to 3 \to \dots \to 10$).
- 얼마 후 네트워크가 복구되어 N5가 클러스터에 다시 연결됩니다.
- 이때 N5는 $Term=10$이 찍힌 메시지를 브로드캐스트합니다.
- 순수 Raft의 핵심 불변식에 따르면, **"어떤 노드든 자신보다 더 높은 임기($Term_{msg} > Term_{self}$)를 가진 메시지를 수신하면, 그 즉시 Follower로 강등되어야 한다!"**
- 그 결과, 지금까지 정상적으로 수많은 클라이언트 트래픽을 처리하던 멀쩡한 리더 N1이 즉시 강등(Step Down)되고, 클러스터 전체에 불필요한 리더 재선출 폭풍이 불어닥치며 대규모 요청 지연(Latency Spike)과 서비스 장애가 발생합니다!

이를 방지하기 위해 최신 분산 시스템(etcd v3, TiKV, Raft PhD dissertation §9.6)은 **사전 투표(Pre-Vote) 프로토콜**과 **리더 리스(Leader Lease)**를 필수로 채택하고 있습니다:
1. **Pre-Vote 프로토콜**:
   - 팔로워는 임기(`currentTerm`)를 올리고 후보자(`CANDIDATE`)로 전환하기 전, 먼저 가상의 임기($Term+1$)로 다른 노드들에게 **"내가 선거를 시작하면 나를 뽑아줄 수 있는가?"**를 묻는 `PreVote`를 요청합니다 (`PRECANDIDATE` 상태).
   - 이때 다른 정상 노드들은 리더로부터 최근에 하트비트를 안정적으로 수신하고 있다면, "현재 멀쩡한 리더가 살아있다!"며 **Pre-Vote를 단호히 거절**합니다 (`ACTIVE_LEADER_EXISTS`).
   - 따라서 고립된 노드는 과반수(Quorum) Pre-Vote를 얻지 못하므로 **임기($Term$)가 결코 증가하지 않습니다!** 네트워크가 복구되어 돌아와도 기존 리더는 아무런 방해 없이 평화롭게 리더십을 유지합니다.
2. **클록 드리프트 경계(Clock Drift Bound) 리더 리스(Leader Lease)**:
   - 클라이언트의 읽기(Read) 요청마다 매번 Raft 로그 복제와 쿼럼 커밋(1 RTT 왕복)을 거치면 읽기 처리량이 급락합니다.
   - 리더는 쿼럼 하트비트 ACK를 확보한 시점부터 다음 공식에 따른 리스 유효 시간 동안 쿼럼 통신 없이 로컬 캐시에서 즉시 선형 일관성 읽기(`LOCAL_LEASE_READ`)를 서비스합니다:
     $$\text{Lease Duration} = \text{min\_election\_timeout} \times (1 - \text{clock\_drift\_bound})$$
   - 리더의 리스가 만료되기 전까지는 어떠한 팔로워도 최소 선거 타임아웃을 넘길 수 없으므로, 두 리더가 동시에 읽기를 처리하는 분할뇌(Split-Brain)가 물리적으로 완벽히 차단됩니다!

여러분은 분산 합의 엔진의 시니어 코어 엔지니어로서, Raft Pre-Vote 위상 전이와 리더 리스 생명주기 및 격리 노드 복귀를 완벽히 모의하는 **Raft Pre-Vote & Leader Lease 분산 시뮬레이터**를 구현해야 합니다!

---

## 2. 상태 머신 및 연산 규칙

### 2.1 노드 상태(Node States)
- `FOLLOWER`: 기본 팔로워 상태.
- `PRECANDIDATE`: 선거 타이머 만료 시 Pre-Vote를 수집하는 중간 상태 (`enable_prevote=True`일 때만 진입, 임기 미증가).
- `CANDIDATE`: 과반수 Pre-Vote 획득 후(또는 `enable_prevote=False`일 때) 실제 임기를 $+1$ 올리고 투표를 요청하는 상태.
- `LEADER`: 과반수 찬성표를 획득하여 선출된 리더 상태.

### 2.2 리더 리스(Leader Lease) 규칙
- 쿼럼 크기: $Quorum = \lfloor N / 2 \rfloor + 1$ ($N$은 총 노드 수).
- 리스 유효 기간:
  $$\text{lease\_duration} = \text{min\_election\_timeout} \times (1 - \text{clock\_drift\_bound})$$
- 리더가 시간 $T$에 쿼럼 이상의 하트비트 ACK를 수신하면:
  $$\text{lease\_valid\_until} = T + \text{lease\_duration}$$
- 클라이언트 읽기 요청(`CLIENT_READ`) 처리:
  - $T_{\text{now}} \le \text{lease\_valid\_until}$ 이면: `status: "SUCCESS"`, `served_via: "LOCAL_LEASE_READ"`.
  - $T_{\text{now}} > \text{lease\_valid\_until}$ 이면: `status: "FALLBACK_REQUIRED"`, `served_via: "QUORUM_READ_INDEX"`.
  - 리더가 아닌 노드에 요청 시: `status: "REJECTED_NOT_LEADER"`, `served_via: "REJECT"`.

### 2.3 Pre-Vote 투표 수락/거절 조건
후보 노드가 $Term_{cand} = Term_{node} + 1$로 보낸 Pre-Vote를 수신한 피어 노드는:
1. **리더 생존 검사**: $(T_{\text{now}} - \text{last\_heartbeat\_time}) < \text{min\_election\_timeout}$ 이면 거절 (`reason: "ACTIVE_LEADER_EXISTS"`).
2. **로그 최신성 검사**: 후보자의 마지막 로그 $(Term_{cand}, Index_{cand})$가 수신자의 마지막 로그보다 뒤처지면 거절 (`reason: "LOG_INCOMPLETE"`).
3. **임기 검사**: $Term_{cand} < Term_{voter} + 1$ 이면 거절 (`reason: "STALE_TERM"`).
4. 위 조건을 모두 통과하면 Pre-Vote 찬성표 부여.
