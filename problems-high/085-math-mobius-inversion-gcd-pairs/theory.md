# 이론 및 해설: 서로소인 쌍의 개수를 한눈에! 뫼비우스 반전 공식 (Mobius Inversion)

### 뫼비우스 반전 공식 (Mobius Inversion Formula)

$$\sum_{i=1}^N \sum_{j=1}^M [\gcd(i, j) == 1] = \sum_{d=1}^{\min(N, M)} \mu(d) \left\lfloor \frac{N}{d} \right\rfloor \left\lfloor \frac{M}{d} \right\rfloor$$
$\lfloor N / d \rfloor$의 평방분할 구간과 $\mu(d)$ 누적합을 결합하여 각 쿼리를 $O(\sqrt{N} + \sqrt{M})$에 해결합니다.
