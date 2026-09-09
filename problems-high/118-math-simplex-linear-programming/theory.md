# 제약 조건의 다포체 꼭짓점을 탐색하라! 심플렉스 알고리즘 (Simplex Algorithm)

## 핵심 개념 및 알고리즘 개요
- **태그**: 수학, 선형대수학, 최적화, 선형 계획법(LP), 심플렉스 알고리즘(Simplex), $O(V)$
- **핵심 요약**: 선형 제약 조건 하에서 목적 함수를 최대화하는 선형 계획법 문제를 단체법(Simplex) 피벗팅으로 최적화합니다.

---

### 선형 계획법 (Linear Programming)과 심플렉스 알고리즘 (Simplex)

선형 제약 조건들 하에서 1차 선형 목적 함수(Objective Function)를 최대화(또는 최소화)하는 문제입니다:
$$\text{Maximize } Z = c_1 x_1 + c_2 x_2 + \dots + c_n x_n$$
$$\text{Subject to } a_{i1} x_1 + a_{i2} x_2 + \dots + a_{in} x_n \le b_i \quad (1 \le i \le m)$$
$$x_j \ge 0 \quad (1 \le j \le n)$$

1. **기하학적 본질**:
   - 제약 조건들을 만족하는 가능 영역(Feasible Region)은 다차원 볼록 다포체(Convex Polytope)를 형성합니다.
   - 선형 함수의 최적해는 반드시 **다포체의 꼭짓점(Extreme Point / Vertex)** 중 하나에서 발생합니다.

2. **심플렉스 타블로(Simplex Tableau)와 피벗팅(Pivoting)**:
   - 부등식 제약에 여유 변수(Slack Variable) $s_i \ge 0$를 도입하여 등식 표준형으로 변환합니다.
   - 목적 함수 계수가 가장 큰 비기저 변수를 **진입 변수(Entering Variable)**로 선택합니다.
   - 비율 판정(Ratio Test, $b_i / a_{ij}$)을 통해 가장 먼저 제약에 걸리는 기저 변수를 **진출 변수(Leaving Variable)**로 선택합니다.
   - 가우스-조던 소거법으로 피벗 행렬 변환을 수행하며 인접한 꼭짓점으로 이동합니다.
   - 모든 목적 함수 계수가 $\le 0$이 되면 최적해에 도달합니다.

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
