# 크누스 최적화 (Knuth's Optimization)

### 1. 적용 조건 (사각부등식과 단조성)
비용 함수 $C(i, j)$가 다음 두 조건을 만족해야 합니다:
1. **단조성(Monotonicity)**: $C(b, c) \le C(a, d)$ ($a \le b \le c \le d$)
2. **사각부등식(Quadrangle Inequality)**: $C(a, c) + C(b, d) \le C(a, d) + C(b, c)$ ($a \le b \le c \le d$)

구간 합 $C(i, j) = \sum_{k=i}^j A_k$는 사각부등식을 등호로 완벽하게 만족합니다.

### 2. $O(N^2)$ 증명
최적 분할점 $opt[i][j]$가 단조성을 가지므로:
$$\sum_{i} (opt[i+1][j] - opt[i][j-1]) = O(N)$$
안쪽 루프의 분기 탐색 횟수가 망원급수(Telescoping Sum)처럼 상쇄되어, 전체 구간 길이에 대한 연산량 합이 $O(N^2)$으로 수렴합니다!
