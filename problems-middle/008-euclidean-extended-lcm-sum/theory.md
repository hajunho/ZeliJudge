# N개 분수의 통분 덧셈과 기약분수

## 1. 두 분수의 덧셈 공식
두 분수 $\frac{a}{b}$와 $\frac{c}{d}$를 더할 때:
$$\frac{a}{b} + \frac{c}{d} = \frac{a \times d + c \times b}{b \times d}$$
더한 후 즉시 $GCD$로 약분하면 분모가 기하급수적으로 커지는 것을 방지할 수 있습니다.

## 2. N개 분수의 누적 덧셈
- 총합을 나타내는 분수를 $\frac{num}{den} = \frac{0}{1}$ 로 시작합니다.
- 새로운 분수 $\frac{a}{b}$가 들어올 때마다:
  - 새 분자: $num \times b + a \times den$
  - 새 분모: $den \times b$
  - $g = GCD(num, den)$으로 나누어 항상 기약분수 상태를 유지합니다.
