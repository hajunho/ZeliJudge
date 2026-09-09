# 사각부등식의 단조성으로 루프를 건너뛰어라! 분할 정복 DP 최적화 (D&C DP Optimization)

## 핵심 개념 및 알고리즘 개요
- **태그**: 동적 계획법(DP), 분할 정복 최적화(D&C DP Optimization), 사각부등식, 몽주 성질, $O(K N \log N)$
- **핵심 요약**: $DP[k][i] = \min (DP[k-1][j] + C(j, i))$ 점화식에서 최적 전이점의 단조성을 이용해 $O(K N^2)$를 $O(K N \log N)$으로 단축합니다.

---

### 분할 정복 DP 최적화 (Divide and Conquer Optimization)

다음 형태의 2차원 동적 계획법 점화식을 고려합니다:
$$DP[k][i] = \min_{0 \le j < i} \big( DP[k-1][j] + C(j, i) \big)$$

1. **사각부등식(Quadrangle Inequality)과 단조성**:
   비용 함수 $C(j, i)$가 사각부등식(Monge Property)
   $$C(a, c) + C(b, d) \le C(a, d) + C(b, c) \quad (a \le b \le c \le d)$$
   을 만족하면, $DP[k][i]$를 최소로 만드는 최적의 전이점 $opt[k][i]$는 **단조 증가(Monotonicity)**합니다:
   $$opt[k][i] \le opt[k][i+1]$$

2. **분할 정복 재귀 계산**:
   - 구간 $[L, R]$의 $i$에 대해 최적 전이점 탐색 범위가 $[opt_L, opt_R]$로 주어집니다.
   - 중앙값 $mid = \lfloor (L + R) / 2 \rfloor$에 대해 $opt_L \le j \le \min(mid-1, opt_R)$ 범위만 탐색하여 $opt[mid]$와 $DP[k][mid]$를 구합니다.
   - 왼쪽 절반 $[L, mid-1]$은 $[opt_L, opt[mid]]$에서, 오른쪽 절반 $[mid+1, R]$은 $[opt[mid], opt_R]$에서 재귀적으로 탐색합니다.
   - 각 레이어 $k$마다 $O(N \log N)$ 시간이 걸리므로, 총 시간 복잡도는 **$O(K N \log N)$**입니다.

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
