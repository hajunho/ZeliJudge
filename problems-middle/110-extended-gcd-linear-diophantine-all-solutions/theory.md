# 일차 디오판토스 방정식 (Linear Diophantine Equation)

### 1. 해의 존재성 판정
$A x + B y = C$에서 $g = \gcd(A, B)$라 할 때:
좌변은 항상 $g$의 배수이므로, **$C \pmod g == 0$일 때만 정수해가 존재**합니다.

### 2. 일반해(General Solution) 공식
확장 유클리드 호제법으로 $A x_0 + B y_0 = g$의 특수해를 구한 뒤 $C/g$를 곱해 기준해 $(x', y')$를 만듭니다:
$$x' = x_0 \cdot \frac{C}{g}, \quad y' = y_0 \cdot \frac{C}{g}$$
모든 정수해 $(x, y)$는 임의의 정수 $k$에 대해 다음과 같이 주어집니다:
$$x = x' + k \cdot \frac{B}{g}, \quad y = y' - k \cdot \frac{A}{g}$$
이 식에서 $x \ge 0$이 되는 최소 정수 $k$를 취하면 유일한 최소 비음수 $x$ 해 순서쌍을 결정할 수 있습니다.
