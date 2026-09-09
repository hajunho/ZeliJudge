# 오일러 피 함수($\phi$)의 소인수분해 공식

### 1. 오일러의 곱셈 공식
자연수 $N$의 서로 다른 소인수들을 $p_1, p_2, \dots, p_k$라고 할 때:

$$\phi(N) = N \times \left(1 - \frac{1}{p_1}\right) \times \left(1 - \frac{1}{p_2}\right) \times \dots \times \left(1 - \frac{1}{p_k}\right)$$

이는 포함-배제의 원리로 간단히 증명됩니다:
- 전체 $N$개에서 각 소인수 $p$의 배수들($N/p$개)을 빼주는 과정이 곱셈 공식으로 정리된 것입니다.

---

### 2. O(sqrt(N)) 계산 알고리즘
```python
ans = N
d = 2
while d * d <= N:
    if N % d == 0:
        while N % d == 0:
            N //= d
        ans -= ans // d  # ans * (1 - 1/d)
    d += 1
if N > 1:
    ans -= ans // N
```
$N$이 최대 10억($10^9$)이라도 $\sqrt{N} \approx 31,622$번의 나눗셈만으로 즉시 답을 구합니다!
