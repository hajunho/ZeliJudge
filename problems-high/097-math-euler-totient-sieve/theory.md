# 이론 및 해설: 서로소의 개수를 한 번에 체로 걸러라! 오일러 피 선형 체

### 오일러 피 선형 체 (Euler's Totient Linear Sieve)

오일러 피 함수 $\phi(n)$은 $1$부터 $n$까지의 자연수 중 $n$과 서로소인 수의 개수를 나타내는 대표적인 곱셈적 함수(Multiplicative Function)입니다.

1. **선형 체 전처리 ($O(N)$)**:
   - 최소 소인수(lp)를 구하는 오일러 체(Euler's Sieve) 과정에서 $\phi(n)$을 동시에 계산할 수 있습니다:
     1. $p$가 소수이면: $\phi(p) = p - 1$
     2. $i$와 소수 $p$를 곱할 때:
        - 만약 $i \bmod p == 0$이면, $p$는 이미 $i$의 소인수이므로:
          $$\phi(i \cdot p) = \phi(i) \cdot p$$
        - 만약 $i \bmod p \ne 0$이면, $\gcd(i, p) = 1$이므로 곱셈적 성질에 의해:
          $$\phi(i \cdot p) = \phi(i) \cdot \phi(p) = \phi(i) \cdot (p - 1)$$
2. **합 계산**:
   - 모든 자연수는 유일한 최소 소인수와 합성수 형태로 단 1번씩만 방문되므로 정확히 $O(N)$ 시간에 전체 $\phi(1 \dots N)$이 완성됩니다.
