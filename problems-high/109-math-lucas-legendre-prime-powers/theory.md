# 거대 팩토리얼 속 소수의 지수를 세어라! 르장드르 공식 (Legendre's Formula & Prime Powers)

## 핵심 개념 및 알고리즘 개요
- **태그**: 수학, 정수론, 르장드르 공식(Legendre's Formula), 소인수분해, 팩토리얼 진법, $O(\log_p N)$
- **핵심 요약**: 르장드르 공식을 통해 거대 정수 $N!$과 중앙 이항계수 $\binom{2N}{N}$에 포함된 소인수 $P$의 지수를 $O(\log_P N)$에 구합니다.

---

### 르장드르 공식 (Legendre's Formula)

양의 정수 $N$과 소수 $P$에 대해, $N!$을 소인수분해했을 때 소수 $P$의 거듭제곱 지수 $E_P(N!)$은 다음과 같습니다:
$$E_P(N!) = \sum_{k=1}^\infty \left\lfloor \frac{N}{P^k} \right\rfloor = \left\lfloor \frac{N}{P} \right\rfloor + \left\lfloor \frac{N}{P^2} \right\rfloor + \left\lfloor \frac{N}{P^3} \right\rfloor + \dots$$

1. **원리**:
   - $1$부터 $N$까지의 수 중에서 $P$의 배수는 $\lfloor N/P \rfloor$개입니다.
   - $P^2$의 배수는 $P$를 한 번 더 제공하므로 $\lfloor N/P^2 \rfloor$개를 더해줍니다.
   - $P^k > N$이 되면 항이 0이 되므로 합산은 $\approx \log_P N$번 만에 종료됩니다.

2. **$P$진법 표현과의 관계**:
   $N$을 $P$진법으로 나타냈을 때의 자릿수 합을 $S_P(N)$이라 하면:
   $$E_P(N!) = \frac{N - S_P(N)}{P - 1}$$

3. **이항계수 $\binom{2N}{N}$에서의 소수 지수**:
   $$\binom{2N}{N} = \frac{(2N)!}{(N!)^2}$$
   이므로,
   $$E_P\left(\binom{2N}{N}\right) = E_P((2N)!) - 2 E_P(N!) = \frac{2 S_P(N) - S_P(2N)}{P - 1}$$
   - 이는 쿰머의 정리(Kummer's Theorem)에 의해 **$N + N$을 $P$진법으로 계산할 때 발생하는 올림(Carry)의 총 횟수**와 정확히 같습니다!

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
