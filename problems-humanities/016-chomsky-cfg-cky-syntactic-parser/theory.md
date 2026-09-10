# [이론 및 배경] 촘스키 구구조 문법(CFG)과 CKY 동적 계획법 통사 파싱의 컴퓨터 언어학적 원리

## 1. 노엄 촘스키와 구구조 문법 (Phrase Structure Grammar)

1957년 노엄 촘스키(Noam Chomsky)는 저서 *Syntactic Structures*에서 행동주의 심리학의 연합설(단어 간 통계적 선형 나열)을 비판하며, 인간 언어의 핵심은 **무한한 표현을 생성하는 유한한 규칙 체계(Discrete Infinity)**와 **위계적 구구조(Hierarchical Structure)**에 있음을 증명했습니다.

문맥 자유 문법(Context-Free Grammar, CFG)은 4-튜플 $G = (V, \Sigma, R, S)$로 정의됩니다:
- $V$: 비말단 기호(Non-terminals: S, NP, VP, PP 등)
- $\Sigma$: 말단 기호(Terminals: 단어 사전)
- $R$: 생성 규칙 집합 ($A \to \alpha$, 여기서 $A \in V$, $\alpha \in (V \cup \Sigma)^*$)
- $S$: 시작 기호 ($S \in V$)

---

## 2. 촘스키 정규형(CNF)과 CKY 알고리즘

일반 CFG는 규칙의 우변 길이가 제각각이어서 파싱 복잡도가 지수적으로 증가할 수 있습니다.
촘스키는 모든 CFG가 의미론적 동등성을 유지하면서 **촘스키 정규형(Chomsky Normal Form, CNF)**으로 변환될 수 있음을 증명했습니다.

### 촘스키 정규형의 2대 규칙 형태
1. **이진 비말단 규칙**: $A \to B \; C$ ($A, B, C \in V$)
2. **단일 말단 규칙**: $A \to a$ ($a \in \Sigma$)

### CKY(Cocke-Younger-Kasami) 동적 계획법
CNF의 이진 분지(Binary Branching) 성질을 활용하면, $N$개 단어로 구성된 문장을 $O(N^3 \cdot |R|)$의 다항 시간 안에 완벽히 구문 분석할 수 있습니다.
- 2차원 차트 $\text{chart}[i][l]$: $i$번째 단어부터 길이 $l$인 부분 문자열 $w_{i \dots i+l-1}$을 유도할 수 있는 비말단 기호 집합.
- **기저 사례 (길이 1)**:
  $$\text{chart}[i][1] = \{ A \mid (A \to w_i) \in R \}$$
- **점화식 (길이 $l = 2 \dots N$)**:
  모든 분할점 $k \in \{1, \dots, l-1\}$에 대해:
  $$\text{chart}[i][l] = \bigcup_{k=1}^{l-1} \{ A \mid (A \to B \; C) \in R, \; B \in \text{chart}[i][k], \; C \in \text{chart}[i+k][l-k] \}$$
- **수락 조건**: $S \in \text{chart}[0][N]$이면 해당 문장은 문법적으로 적격(Grammatical).

---

## 3. 자연어의 통사적 중의성과 카탈랑 수 (Catalan Numbers)

프로그래밍 언어의 문법은 모호성이 없도록 설계(LL, LR 파서)되지만, 자연어는 구조적 중의성이 기하급수적으로 폭발합니다.
예를 들어 전치사구(PP)가 $k$개 연쇄 결합된 문장:
$$\text{NP} \to \text{NP} \; \text{PP}_1 \; \text{PP}_2 \; \dots \; \text{PP}_k$$
이 문장이 가질 수 있는 유효한 이진 구구조 트리의 개수는 수학의 **카탈랑 수(Catalan Number)**를 따릅니다:
$$C_k = \frac{1}{k+1} \binom{2k}{k}$$
- $k=1$ (전치사구 1개): $C_1 = 1$ (동사구 부착과 명사구 부착 2가지 해석)
- $k=2$ (전치사구 2개): $C_2 = 2 \to C_3 = 5$개 트리

---

## 4. 확률적 CFG (PCFG)와 비터비(Viterbi) 중의성 해소

수많은 중의적 트리 중 인간 화자가 의도한 가장 개연성 높은 트리를 선택하기 위해 각 생성 규칙에 조건부 확률을 부여합니다:
$$\sum_{\alpha} P(A \to \alpha) = 1.0$$
트리 $T$의 전체 확률은 포함된 모든 규칙 확률의 곱으로 정의됩니다:
$$P(T) = \prod_{(A \to \alpha) \in T} P(A \to \alpha)$$
CKY 차트 내에서 각 비말단 기호마다 최대 확률과 역추적 포인터(Backpointer)를 유지하는 **Viterbi CKY 알고리즘**을 통해, 가장 높은 결합 확률을 지닌 최적 구구조 수형도 $\hat{T} = \arg\max_T P(T)$를 단번에 도출합니다.
