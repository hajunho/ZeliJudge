# 이론 및 해설: 선형 점화식의 10^18번째 항을 빠르게! 키타마사법 (Kitamasa Method)

### 키타마사법 (Kitamasa Method)

선형 점화식 $A_n = \sum_{i=1}^K c_i A_{n-i}$에 대해 $N$번째 항을 구하는 가장 대표적인 방법은 $K 	imes K$ 동반 행렬(Companion Matrix)의 거듭제곱으로 $O(K^3 \log N)$이 걸립니다.
키타마사법은 이를 다항식 잉여환(Quotient Ring) $\mathbb{Z}[x] / \langle P(x) angle$ 상의 거듭제곱으로 바꾸어 $O(K^2 \log N)$에 해결합니다.

1. **특성 다항식**:
   - $P(x) = x^K - c_1 x^{K-1} - c_2 x^{K-2} - \dots - c_K$
   - $x^N mod P(x) = \sum_{j=0}^{K-1} d_j x^j$를 계산합니다.
   - 케일리-해밀턴 정리(Cayley-Hamilton Theorem)에 의해 $A_N = \sum_{j=0}^{K-1} d_j A_j \pmod{10^9+7}$로 바로 구해집니다!
2. **다항식 거듭제곱 분할 정복**:
   - $x^N$을 구할 때 이진 분할 정복으로 거듭제곱을 수행하며, 두 $K$차 미만 다항식의 곱 $O(K^2)$ 후 $P(x)$로 나눈 나머지 $O(K^2)$를 반복합니다.
