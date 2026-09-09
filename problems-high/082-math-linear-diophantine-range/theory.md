# 이론 및 해설: 제한된 범위 내의 정수해는 몇 개일까? 선형 디오판토스 방정식 (Diophantine Range)

### 선형 디오판토스 방정식의 구간 해 (Linear Diophantine Equation)

방정식 $Ax + By = C$의 정수해를 구하는 문제입니다.
$g = \gcd(A, B)$일 때, $C$가 $g$의 배수가 아니면 해가 존재하지 않습니다.

1. **특수해와 일반해**:
   - 확장 유클리드로 $A x_0 + B y_0 = C$의 특수해를 구합니다.
   - 일반해: $x = x_0 + k \frac{B}{g}, y = y_0 - k \frac{A}{g}$
2. **구간 제한과 $k$의 범위**:
   - $x_{min} \le x \le x_{max}$ 및 $y_{min} \le y \le y_{max}$에서 $k$의 유효 범위를 교집합하여 $O(1)$에 개수를 산출합니다.
