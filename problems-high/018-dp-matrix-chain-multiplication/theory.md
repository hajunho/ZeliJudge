# 연쇄 행렬 곱셈 (Matrix Chain Multiplication)

## 1. 구간 DP 점화식
`dp[i][j]`를 $i$번째 행렬부터 $j$번째 행렬까지 곱하는 데 드는 최소 곱셈 횟수라 하면:
- 기저 사례: `dp[i][i] = 0`
- 구간 분할 $k$ ($i \le k < j$):
  $$\text{dp}[i][j] = \min_{i \le k < j} (\text{dp}[i][k] + \text{dp}[k+1][j] + r_i \times c_k \times c_j)$$

## 2. 계산 순서
구간의 길이 `len = 2`부터 `N`까지 점진적으로 늘려가며 부분 문제들을 해결합니다.
상태 수 $O(N^2)$, 각 상태 전이 $O(N)$이므로 총 시간 복잡도는 $O(N^3)$입니다.