# 뫼비우스 합을 아원형 속도로 정복하라! 메르텐스 함수 (Mertens Function Du Sieve)

## 핵심 개념 및 알고리즘 개요
- **태그**: 수학, 정수론, 메르텐스 함수(Mertens Function), 뫼비우스 함수, 두 체(Du Sieve), $O(N^{2/3})$
- **핵심 요약**: 뫼비우스 함수의 부분합인 메르텐스 함수 $M(N) = \sum_{i=1}^N \mu(i)$를 $O(N^{2/3})$에 고속 계산합니다.

---

### 메르텐스 함수 (Mertens Function)와 두 체 (Du Sieve)

뫼비우스 함수 $\mu(n)$의 $1$부터 $N$까지의 누적합을 **메르텐스 함수(Mertens Function)**라고 합니다:
$$M(N) = \sum_{i=1}^N \mu(i)$$

1. **디리클레 합성곱 항등식**:
   $$\sum_{d \mid n} \mu(d) = [n = 1]$$
   양변을 $1$부터 $N$까지 합산하면:
   $$\sum_{i=1}^N \sum_{d \mid i} \mu(d) = \sum_{d=1}^N \mu(d) \left\lfloor \frac{N}{d} \right\rfloor = 1$$
   $d=1$인 항 $M(N)$을 분리하면 점화식을 얻습니다:
   $$M(N) = 1 - \sum_{d=2}^N \mu(d) \left\lfloor \frac{N}{d} \right\rfloor = 1 - \sum_{d=2}^N M\left(\left\lfloor \frac{N}{d} \right\rfloor\right)$$

2. **두 체(Du Sieve) 아원형(Sublinear) 최적화**:
   - $\lfloor N/d \rfloor$ 값은 최대 $2\sqrt{N}$개의 서로 다른 값만 가집니다(정수 나눗셈 블록 분할).
   - $N^{2/3}$까지의 작은 $M(i)$는 선형 체(Linear Sieve)로 $O(N^{2/3})$에 미리 전처리합니다.
   - $N^{2/3}$보다 큰 값들은 메모이제이션(해시 맵)을 적용하여 위 재귀식을 계산합니다.
   - 전체 시간 복잡도는 놀랍게도 **$O(N^{2/3})$**으로 줄어들어 $N = 10^9$도 0.1초 내에 계산 가능합니다.

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
