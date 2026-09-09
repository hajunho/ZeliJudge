# 무한 급수를 미분하고 적분하라! 형식적 멱급수의 미적분 (Formal Power Series Calculus)

## 핵심 개념 및 알고리즘 개요
- **태그**: 수학, 다항식, 형식적 멱급수(FPS), 미분(Derivative), 부정적분(Integral), $O(N)$
- **핵심 요약**: 모듈러 $998,244,353$ 상에서 주어진 다항식의 도함수와 부정적분을 $O(N)$ 선형 시간에 계산합니다.

---

### 형식적 멱급수(FPS)의 미분과 적분

다항식 $P(x) = \sum_{i=0}^N a_i x^i = a_0 + a_1 x + a_2 x^2 + \dots + a_N x^N$에 대해:

1. **도함수 (Derivative)**:
   $$P'(x) = \sum_{i=1}^N i \cdot a_i x^{i-1} = a_1 + 2 a_2 x + 3 a_3 x^2 + \dots + N a_N x^{N-1}$$
   - 계수는 $(i \times a_i) \pmod M$으로 $O(N)$에 직접 계산됩니다.
   - 차수는 $N-1$차 다항식이 됩니다. ($N=0$인 경우 0)

2. **부정적분 (Indefinite Integral)**:
   적분상수 $C = 0$일 때,
   $$\int P(x) dx = \sum_{i=0}^N \frac{a_i}{i+1} x^{i+1} = a_0 x + \frac{a_1}{2} x^2 + \dots + \frac{a_N}{N+1} x^{N+1}$$
   - $1 \le k \le N+1$에 대해 모듈러 역원 $k^{-1} \pmod M$이 필요합니다.
   - **선형 모듈러 역원 전처리**:
     $$\text{inv}[1] = 1, \quad \text{inv}[i] = (M - \lfloor M/i \rfloor) \cdot \text{inv}[M \bmod i] \pmod M$$
     을 이용하면 $1$부터 $N+1$까지의 모든 역원을 $O(N)$에 전처리할 수 있습니다.
   - 따라서 미분과 적분 모두 전체 $O(N)$ 시간에 수행됩니다.

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
