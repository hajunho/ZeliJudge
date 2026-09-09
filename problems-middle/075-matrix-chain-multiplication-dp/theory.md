# 구간 DP (Interval DP)와 행렬 곱셈 순서 최적화

### 1. 부분 문제 정의 (Optimal Substructure)
$i$번째 행렬부터 $j$번째 행렬까지의 곱 $A_i \dots A_j$의 최소 곱셈 횟수를 $DP(i, j)$라 합시다.
마지막에 곱해지는 결합 지점을 $k$ ($i \le k < j$)라고 하면:
$$DP(i, j) = \min_{i \le k < j} \Big( DP(i, k) + DP(k+1, j) + r_i \cdot c_k \cdot c_j \Big)$$

- 기저 조건: $DP(i, i) = 0$ (행렬 1개는 곱셈 불필요)
- 계산 순서: 구간의 길이 $L = 2, 3, \dots, N$ 순서대로 상향식 계산.
- 시간 복잡도: 상태 개수 $O(N^2) \times$ 분기점 탐색 $O(N) = O(N^3)$.
