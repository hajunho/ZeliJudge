# 확장 유클리드 호제법과 모듈러 역원

### 1. 베주 항등식(Bézout's Identity)
$A$와 $B$의 일차 결합으로 만들 수 있는 가장 작은 양의 정수는 바로 $\gcd(A, B)$입니다.

---

### 2. 확장 유클리드 호제법의 재귀적 원리
유클리드 나눗셈 정리: $A = Q \times B + R$ ($R = A \% B$)  
만약 작은 문제 $B \times x_1 + R \times y_1 = g$의 해 $(x_1, y_1)$을 알고 있다면:

$$B \times x_1 + (A - Q \times B) \times y_1 = g$$
$$A \times y_1 + B \times (x_1 - Q \times y_1) = g$$

따라서 현재 단계의 해 $(x, y)$는 다음과 같이 완벽하게 유도됩니다:
$$x = y_1$$
$$y = x_1 - \lfloor A / B \rfloor \times y_1$$

기저 조건($B = 0$)에서는 $A \times 1 + 0 \times 0 = A$이므로 `(1, 0, A)`를 반환하면 됩니다.

---

### 3. 컴퓨터 과학에서의 결정적 활용: RSA 암호학
두 수 $A$와 $M$이 서로소($\gcd(A, M) = 1$)일 때:
$$A \times x + M \times y = 1 \iff A \times x \equiv 1 \pmod M$$
즉, $x$는 $A$의 **모듈러 곱셈 역원(Modular Multiplicative Inverse)**이 되며, 이는 현대 인터넷 보안의 기둥인 **RSA 공개키 암호 알고리즘의 비밀키 생성**에 핵심적으로 쓰입니다!
