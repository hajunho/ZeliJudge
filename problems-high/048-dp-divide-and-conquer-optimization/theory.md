# 분할 정복 최적화 (D&C Optimization)

## 1. 적용 조건
- 점화식이 $DP[k][i] = \min_{j < i} (DP[k-1][j] + C(j+1, i))$ 형태를 띠며,
- 최적의 전이 위치 $opt[k][i]$가 $i$에 대해 단조 증가($opt[k][i] \le opt[k][i+1]$)할 때 적용할 수 있습니다.

## 2. 분할 정복 설계
- 함수 `compute(k, l, r, opt_l, opt_r)`를 호출하여 구간 $[l, r]$의 중앙값 $mid = (l + r) / 2$의 최적 분할점 $opt$를 $[opt_l, opt_r]$ 범위에서 탐색합니다.
- $mid$의 최적점 $opt$가 구해지면, 좌측 $[l, mid-1]$은 $[opt_l, opt]$에서, 우측 $[mid+1, r]$은 $[opt, opt_r]$에서 재귀적으로 분할 정복합니다.
- 매 $k$마다 $O(N \log N)$이 소요되어 총 $O(K N \log N)$에 완료됩니다.