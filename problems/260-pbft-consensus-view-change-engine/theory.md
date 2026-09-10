# [이론 및 배경] 비잔틴 장애 허용(BFT) 합의와 PBFT 프로토콜 아키텍처

## 1. 비잔틴 장군 문제(Byzantine Generals Problem)와 BFT의 의의

1982년 레슬리 램포트(Leslie Lamport), 로버트 쇼스탁(Robert Shostak), 마샬 피스(Marshall Pease)가 제시한 **비잔틴 장군 문제**는 분산 컴퓨팅의 궁극적인 신뢰 딜레마를 모델링합니다:
> *"적국 도시를 포위한 $N$명의 장군들이 메시지를 전달하는 전령을 통해 공격 시각을 합의해야 한다. 그러나 장군들 중 일부는 적과 내통하는 배신자(Byzantine)이며, 이들은 서로 다른 장군에게 거짓 메시지를 보내거나 침묵하여 합의를 와해시키려 한다."*

### 1.1 CFT vs BFT의 근본적 차이
| 구분 | 크래시 장애 허용 (CFT) | 비잔틴 장애 허용 (BFT) |
|---|---|---|
| **대표 알고리즘** | Paxos, Raft, Multi-Raft | PBFT, Tendermint, HotStuff |
| **가정된 고장 모델** | Crash-Stop, Crash-Recovery, Network Partition (정직한 오류) | 임의 행동, 메시지 변조, 이중 제안, 침입자 (악의적 공격) |
| **최소 노드 수** | $2f + 1$ (과반수 정족수) | $3f + 1$ (슈퍼 메이저리티 $2/3$) |
| **정족수 크기** | $f + 1$ | $2f + 1$ |
| **메시지 복잡도** | $\mathcal{O}(N)$ (리더 중심 스타 토폴로지) | $\mathcal{O}(N^2)$ (올-투-올 교차 검증) |

---

## 2. 왜 $3f + 1$개의 노드가 필요한가? (수학적 엄밀 증명)

전체 노드 수가 $N$이고 악의적인 비잔틴 노드가 최대 $f$개 존재할 때:
1. $f$개의 노드가 완전히 무응답(Crash 또는 Silent Drop)할 수 있으므로, 프로토콜이 응답을 기다릴 수 있는 최대 노드 수는 $N - f$개입니다.
2. 그런데 응답한 $N - f$개의 노드 중에도 최대 $f$개의 비잔틴 노드가 교묘하게 거짓 정보를 보내며 포함되어 있을 수 있습니다.
3. 따라서 응답한 노드 중 정직한 노드의 수는 최소 $(N - f) - f = N - 2f$개입니다.
4. 비잔틴 노드들의 거짓 표($f$표)보다 정직한 노드들의 올바른 표($N - 2f$표)가 엄격하게 많아야만 다수결로 올바른 합의를 보장할 수 있습니다:
   $$N - 2f > f \implies N > 3f \implies N \ge 3f + 1$$
따라서 $f=1$일 때 최소 4개, $f=2$일 때 최소 7개, $f=3$일 때 최소 10개의 노드가 필수적입니다.

---

## 3. PBFT 3단계 합의(Three-Phase Agreement)의 동작 원리

PBFT(Castro & Liskov, 1999)는 3단계의 메시지 교환을 통해 비잔틴 리더의 위조를 방어합니다:

```
Client      Primary (0)      Backup (1)      Backup (2)      Backup (3) [Byzantine]
  |              |                |                |                |
  |---Request--->|                |                |                |
  |              |--Pre-Prepare-->|--Pre-Prepare-->|--Pre-Prepare-->| (Drops or forges)
  |              |                |                |                |
  |              |<---Prepare---->|<---Prepare---->|<---Prepare---->| (All-to-all: 2f needed)
  |              |   [Prepared]   |   [Prepared]   |   [Prepared]   |
  |              |                |                |                |
  |              |<----Commit---->|<----Commit---->|<----Commit---->| (All-to-all: 2f+1 needed)
  |              |  [Committed]   |  [Committed]   |  [Committed]   |
  |              |   (Execute)    |   (Execute)    |   (Execute)    |
  |<--Reply------|-------Reply----|-------Reply----|                | (Client waits f+1 replies)
```

1. **Pre-Prepare**: 리더가 순번 $n$과 다이제스트 $d$를 부여하여 제안.
2. **Prepare ($2f$ Quorum)**:
   - 각 노드가 Pre-Prepare를 수락하면 Prepare 메시지를 브로드캐스트.
   - $2f$개의 유효한 Prepare가 모이면 **Prepared Certificate**가 완성됩니다.
   - **보장하는 성질**: 동일한 뷰 $v$ 내에서 두 개의 서로 다른 요청이 동일한 시퀀스 번호 $n$으로 Prepared 되는 것은 불가능합니다.
3. **Commit ($2f + 1$ Quorum)**:
   - Prepared 상태에 도달한 노드는 Commit 메시지를 브로드캐스트.
   - $2f + 1$개의 Commit이 모이면 **Committed-Local Certificate**가 완성됩니다.
   - **보장하는 성질**: 시스템 내의 최소 $f+1$개의 정직한 노드가 Prepared 상태에 도달했음이 전역적으로 보장됩니다. 향후 뷰 체인지가 발생하더라도 이 커밋된 순번의 내용은 영원히 덮어쓰이지 않습니다.

---

## 4. 비잔틴 공격 유형과 방어 메커니즘

### 4.1 이중 제안 공격 (Equivocation / Double-Proposing)
비잔틴 리더가 노드 집합 $A$에는 트랜잭션 $lpha$를, 노드 집합 $B$에는 트랜잭션 $eta$를 Pre-Prepare로 보냅니다:
- 노드들은 Prepare 단계에서 서로의 다이제스트를 교차 검증합니다.
- 집합 $A$의 노드들은 다이제스트 $d(lpha)$의 Prepare만 발행하고, 집합 $B$는 $d(eta)$의 Prepare만 발행합니다.
- 정직한 노드가 한쪽에 최대 $2f$ 미만으로 분할되므로, 어느 쪽도 $2f$개의 Prepare 정족수를 달성할 수 없습니다.
- 따라서 불일치 상태에서 커밋이 원천 차단됩니다.

### 4.2 뷰 체인지 (View Change) 프로토콜
리더가 이중 제안을 시도하여 시스템이 멈추거나, 리더가 의도적으로 요청을 처리하지 않고 지연(Liveness Attack)시키면:
1. 각 노드의 요청 실행 타이머가 만료됩니다.
2. 노드들은 현재 뷰의 리더를 불신임하고 `<VIEW-CHANGE, v+1, ...>` 메시지를 브로드캐스트합니다.
3. 새로운 리더 $p' = (v+1) mod R$는 $2f + 1$개의 View-Change 메시지를 수집하여 `NEW-VIEW` 메시지를 생성하고 클러스터를 정상 상태(`NORMAL`)로 복구합니다.
4. 비잔틴 노드가 아무리 방해하더라도 최소 $2f+1$개의 정직한 투표가 모이면 새로운 뷰로의 전이가 수학적으로 보장됩니다.

---

## 5. 알고리즘 복잡도 및 현대적 확장

- **메시지 복잡도**:
  - 정상 경로(Normal Case): Prepare $N 	imes (N-1)$ + Commit $N 	imes (N-1) \implies \mathcal{O}(N^2)$
  - 뷰 체인지 경로: $\mathcal{O}(N^3)$
- **현대적 개선 (HotStuff, Tendermint)**:
  - PBFT의 $\mathcal{O}(N^2)$ 올-투-올 통신을 리더 수집 방식(Threshold Signature 기반 집약 서명)으로 개선하여 $\mathcal{O}(N)$의 선형 뷰 체인지 복잡도를 달성한 것이 현대 블록체인(Aptos, Sui, Diem) BFT의 기반이 되었습니다.
