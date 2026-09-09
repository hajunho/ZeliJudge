# 확장 유클리드 호제법과 디오판토스 방정식

## 1. 베주 항등식 (Bézout's Identity)
두 정수 $A, B$에 대해 $Ax + By = \gcd(A, B)$를 만족하는 정수 쌍 $(x_0, y_0)$는 유클리드 호제법의 역연산 과정을 통해 항상 찾을 수 있습니다.

## 2. 일반해와 최소 비음수 $x$
$g = \gcd(A, B)$라 할 때, $C$가 $g$의 배수가 아니면 해가 없습니다.
$C = g \cdot k$일 때 특수해는 $(x_0 k, y_0 k)$가 되며, 일반해는 다음과 같습니다:
$$x = x' + t \cdot \frac{B}{g}, \quad y = y' - t \cdot \frac{A}{g} \quad (t \in \mathbb{Z})$$
$x \ge 0$인 최소 $x$는 $x \bmod (B/g)$ 연산으로 즉시 도출할 수 있습니다.