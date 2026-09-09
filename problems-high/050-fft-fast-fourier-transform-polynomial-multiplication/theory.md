# 고속 푸리에 변환 (FFT, Fast Fourier Transform)

## 1. 계수 표현과 점 값 표현 (Point-Value Representation)
- 차수 $N$인 다항식은 서로 다른 $N+1$개의 점에서 평가한 점 값들로 유일하게 결정됩니다.
- 점 값 표현에서의 곱셈은 각 점에서의 값을 단순히 곱하기만 하면 되므로 $O(N)$에 끝납니다.

## 2. 쿨리-튜키 (Cooley-Tukey) 분할 정복
- 짝수 차수 항들과 홀수 차수 항들로 분할하여 복소수 $e^{2\pi i / N}$의 대칭성을 활용합니다:
  $$A(x) = A_{even}(x^2) + x A_{odd}(x^2)$$
- $T(N) = 2T(N/2) + O(N)$ 점화식에 의해 $O(N \log N)$ 시간에 변환(FFT) 및 역변환(IFFT)이 완료됩니다.