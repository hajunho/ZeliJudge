# 문제 224 이론: Raft 분산 합의 동적 멤버십 변경과 비투표 학습자(Non-Voting Learner) 노드 수렴 공학

---

## 1. 정적 클러스터에서 동적 멤버십 변경으로의 진화

기본 Raft 프로토콜(Diego Ongaro & John Ousterhout, USENIX ATC 2014)은 클러스터 구성 노드가 고정되어 있다고 가정합니다.
그러나 운영 환경에서는 서버 증설, 노드 교체, 장애 장비 퇴역(Decommission) 등 멤버십 변경이 필수적입니다.

### 1.1 짝수 노드와 가용성 절벽(Availability Cliff)
Raft의 과반수 쿼럼 크기는 $Q(N) = \lfloor N / 2 \rfloor + 1$ 입니다.
- $N = 3 \implies Q = 2$. 허용 장애 노드 수 $F = 3 - 2 = 1$대.
- $N = 4 \implies Q = 3$. 허용 장애 노드 수 $F = 4 - 3 = 1$대.
- $N = 5 \implies Q = 3$. 허용 장애 노드 수 $F = 5 - 3 = 2$대.

**중요한 통찰**: 3노드에서 4노드로 노드를 1대 추가하더라도 허용 가능한 고장 노드 수는 여전히 1대($F=1$)입니다.
더 심각한 것은, 추가된 노드가 아직 로그를 복제받지 못한 상태(Cold Node)라면 실질적으로 투표할 수 없으므로 허용 장애 노드 수가 **$F = 1 - 1 = 0$대**로 추락합니다.
즉, 기존 3대 중 단 1대만 일시 지연되더라도 즉시 쿼럼이 붕괴하는 **가용성 절벽(Availability Cliff)**이 발생합니다.

---

## 2. Diego Ongaro의 해결책: 비투표 학습자(Non-Voting Learner)

Diego Ongaro는 그의 박사 학위 논문(*Consensus: Bridging Theory to Practice*, 2014, Section 4.2.1)에서 콜드 노드 추가 문제를 해결하기 위해 **Learner** 역할을 도입했습니다.

```
 [Raft Node State Machine with Learner Extension]

        ┌──────────────┐
        │   LEARNER    │ (Replicates Logs, Cannot Vote, Not in Quorum)
        └──────┬───────┘
               │ Catch-up Rounds complete & Gap <= Threshold
               ▼ (Atomic ConfChangeAddNode)
        ┌──────────────┐     Timeout / Split Vote    ┌──────────────┐
   ───► │   FOLLOWER   │ ──────────────────────────► │  CANDIDATE   │
        └──────▲───────┘                             └──────┬───────┘
               │            Discovers Leader                │ Votes from Majority
               │ ────────────────────────────────────────── │
               │               ┌──────────────┐             │
               └────────────── │    LEADER    │ ◄───────────┘
                               └──────────────┘
```

### 2.1 학습자의 특권과 제약
1. **쿼럼 불포함**: 클러스터가 3대일 때 학습자 2대를 추가해도 투표 노드는 여전히 3대이며 쿼럼은 2대입니다.
2. **로그 수신**: 리더는 일반 팔로워와 동일하게 학습자에게 `AppendEntries`와 `InstallSnapshot`을 전송합니다.
3. **선거 불참**: 학습자는 타이머가 만료되어도 후보자(Candidate)로 전환되지 않으며, `RequestVote`에 투표하지 않습니다.

---

## 3. 다단계 라운드 동기화와 기하급수적 수렴 수학

리더가 학습자를 언제 투표자로 승격시켜야 할까요?
리더는 동기화 과정을 여러 라운드($R_1, R_2, \dots$)로 분할하여 추적합니다.

### 3.1 수렴 수학 모델
- $G_0$: 초기 동기화 필요 로그 수 (Commit Index - Snapshot Index).
- $V_{\text{ingest}}$: 학습자의 초당 로그 복제 속도.
- $V_{\text{write}}$: 리더로 유입되는 초당 신규 클라이언트 트랜잭션 쓰기 속도.

라운드 $r$의 소요 시간: $t_r = \frac{G_{r-1}}{V_{\text{ingest}}}$
라운드 $r$ 동안 리더에 새로 쌓인 로그: $G_r = V_{\text{write}} \times t_r = G_{r-1} \times \left( \frac{V_{\text{write}}}{V_{\text{ingest}}} \right)$

수렴 비(Convergence Ratio) $\alpha = \frac{V_{\text{write}}}{V_{\text{ingest}}}$ 라 할 때:
$$G_r = G_0 \times \alpha^r$$

1. **$\alpha < 1$ (수렴 조건, $V_{\text{write}} < V_{\text{ingest}}$)**:
   - 매 라운드마다 격차가 등비수열로 감소합니다.
   - 수 라운드(보통 2~3 라운드) 내에 격차가 $G_r \le \text{threshold}$로 축소됩니다.
   - 안전한 원자적 승격이 보장됩니다.
2. **$\alpha \ge 1$ (발산/기아 조건, $V_{\text{write}} \ge V_{\text{ingest}}$)**:
   - 학습자가 따라잡는 속도보다 리더에 새 로그가 쌓이는 속도가 더 빠르거나 같습니다.
   - 라운드를 아무리 반복해도 격차가 줄어들지 않고 영원히 동기화에 갇히는 **학습자 기아 루프(Learner Starvation Loop)**가 발생합니다.

---

## 4. 실무 구현체: etcd, TiKV, CockroachDB

- **etcd 3.4+**: `etcdctl member add node4 --learner` 명령어로 추가 후, 백엔드 메트릭을 관찰하여 `etcdctl member promote node4`로 승격합니다.
- **TiKV (Placement Rules)**: 새로운 TiKV 노드가 투표권 없이 Learner로 먼저 복제본을 다운로드받아 Raft Region을 워밍업합니다.
- **CockroachDB**: 레인지 복제본 이동 시 Non-Voting Replicas로 사전 스트리밍 후 리더 리스(Lease)를 이전합니다.
