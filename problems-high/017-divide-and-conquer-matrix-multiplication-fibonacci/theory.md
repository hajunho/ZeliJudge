# 행렬 거듭제곱과 분할 정복 (Matrix Exponentiation)

## 1. 선형 점화식의 행렬 표현
$$\begin{pmatrix} F_{n+1} \\ F_n \end{pmatrix} = \begin{pmatrix} 1 & 1 \\ 1 & 0 \end{pmatrix} \begin{pmatrix} F_n \\ F_{n-1} \end{pmatrix}$$
따라서 다음과 같이 거듭제곱 꼴로 정리됩니다:
$$\begin{pmatrix} F_{n+1} & F_n \\ F_n & F_{n-1} \end{pmatrix} = \begin{pmatrix} 1 & 1 \\ 1 & 0 \end{pmatrix}^n$$

## 2. 분할 정복 거듭제곱
행렬 $A^n$을 구할 때:
- $n$이 짝수이면: $A^n = (A^{n/2})^2$
- $n$이 홀수이면: $A^n = A \times A^{n-1}$
이를 통해 $N = 10^{18}$이어도 약 60번의 $2 \times 2$ 행렬 곱셈만으로 정확한 나머지를 도출할 수 있습니다.