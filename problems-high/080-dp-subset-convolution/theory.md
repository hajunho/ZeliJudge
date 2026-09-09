# 이론 및 해설: 서로소 부분집합들의 완벽한 결합! 부분집합 합성곱 (Subset Convolution)

### 부분집합 합성곱 (Fast Subset Convolution)

크기 $2^N$인 두 배열 $A, B$에 대해 다음과 같은 합성곱
$$C[k] = \sum_{\substack{i \text{ OR } j = k \\ i \text{ AND } j = 0}} A[i] \cdot B[j] \pmod{10^9+7}$$
을 구하는 문제입니다.

1. **원리 ($O(N^2 2^N)$)**:
   - $i \text{ AND } j = 0 \iff \text{popcount}(i) + \text{popcount}(j) = \text{popcount}(k)$.
   - 팝카운트별로 분리한 2차원 배열에 대해 SOS DP(제타 변환)를 적용하고 점별 다항식 곱셈 후 역변환(뫼비우스 변환)을 취합니다.
