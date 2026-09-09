# 참과 거짓의 그물망을 풀어라! 2-SAT 문제와 강결합 컴포넌트 (2-SAT SCC)

## 핵심 개념 및 알고리즘 개요
- **태그**: 그래프, 2-SAT(2-Satisfiability), 강결합 컴포넌트(SCC), 타잔(Tarjan), 위상 정렬, $O(V + E)$
- **핵심 요약**: 불리언 2-CNF 논리식을 함의 그래프(Implication Graph)로 변환하고 SCC를 통해 충족 가능성 및 변수 참/거짓 해를 구합니다.

---

### 2-SAT (2-Satisfiability)과 함의 그래프

2-SAT은 각 절(Clause)이 최대 2개의 리터럴(Literal)의 논리합(OR)으로 이루어진 논리식(2-CNF)을 참으로 만드는 진리값 할당을 찾는 문제입니다:
$$(x_i \lor x_j) \land (\neg x_k \lor x_m) \land \dots$$

1. **함의 관계(Implication)로의 변환**:
   - 논리합 $(A \lor B)$는 동치인 두 함의식으로 표현됩니다:
     $$\neg A \implies B \quad \text{and} \quad \neg B \implies A$$
   - 변수 $x_i$에 대해 $x_i$와 $\neg x_i$를 각각 하나의 방향 그래프 정점으로 생성합니다 ($2N$개 정점).
   - 각 절 $(A \lor B)$마다 두 개의 방향 간선 $(\neg A \to B)$와 $(\neg B \to A)$를 추가합니다.

2. **충족 가능성 판정 (SCC)**:
   - 그래프에서 강결합 컴포넌트(SCC)를 구합니다.
   - 만약 어떤 변수 $x_i$에 대해 **$x_i$와 $\neg x_i$가 동일한 SCC에 속한다면**, $x_i \implies \neg x_i$이고 $\neg x_i \implies x_i$이므로 모순이 발생하여 **만족 불가능(UNSAT, 0)**입니다.
   - 모든 변수에 대해 서로 다른 SCC에 속한다면 **만족 가능(SAT, 1)**입니다.

3. **진리값 할당 복원**:
   - SCC의 위상 정렬 역순(Tarjan SCC 번호 오름차순)으로 먼저 도달하는 정점에 거짓(False)을, 나중에 도달하는 정점에 참(True)을 부여합니다:
     $$\text{scc}[x_i] < \text{scc}[\neg x_i] \implies x_i = \text{True}$$
     $$\text{scc}[x_i] > \text{scc}[\neg x_i] \implies x_i = \text{False}$$

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
