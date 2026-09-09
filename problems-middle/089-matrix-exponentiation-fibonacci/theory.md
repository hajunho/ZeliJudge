# 행렬 거듭제곱을 이용한 선형 점화식 고속 계산 ($O(\log N)$)

### 1. 상태 전이 행렬 (State Transition Matrix)
인접한 두 항 사이의 관계를 벡터와 행렬로 모델링합니다:
$$\begin{pmatrix} F_{n+1} \\ F_n \end{pmatrix} = \begin{pmatrix} 1 & 1 \\ 1 & 0 \end{pmatrix} \begin{pmatrix} F_n \\ F_{n-1} \end{pmatrix}$$
이를 $n$번 누적 적용하면:
$$\begin{pmatrix} F_{n+1} & F_n \\ F_n & F_{n-1} \end{pmatrix} = \begin{pmatrix} 1 & 1 \\ 1 & 0 \end{pmatrix}^n$$

### 2. 분할 정복 행렬 거듭제곱
$A^N$을 구할 때:
- $N$이 짝수이면 $A^N = (A^{N/2})^2$
- $N$이 홀수이면 $A^N = A \times (A^{(N-1)/2})^2$
의 이진 거듭제곱을 취하면, $2 \times 2$ 행렬 곱셈 $O(1)$ 연산을 $\log_2 N$번만 수행하므로 **$O(\log N)$** 시간에 $N = 10^{15}$까지도 1ms 만에 계산할 수 있습니다!
