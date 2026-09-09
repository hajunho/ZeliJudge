# 서로소(Coprime / Relatively Prime)와 유클리드 호제법

두 자연수 $A$와 $B$의 **최대공약수(GCD)가 1**일 때, 두 수를 **서로소(Coprime)**라고 부릅니다.
즉, 1 이외에는 공통된 약수가 전혀 없다는 뜻입니다.

## 1. 서로소 판별
- $GCD(8, 9) = 1$ $\rightarrow$ 서로소입니다! (8=2*2*2, 9=3*3)
- $GCD(6, 9) = 3 \ne 1$ $\rightarrow$ 서로소가 아닙니다.

## 2. 유클리드 호제법 (Euclidean Algorithm)
파이썬에서는 `math.gcd(a, b)`를 사용하면 눈 깜짝할 사이에 최대공약수를 구할 수 있습니다.
직접 구현할 때도:
```python
def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a
```

## 3. 모든 쌍 탐색하기
$N$개의 수에서 두 개를 고르는 모든 순서쌍 $(i, j)$ ($0 \le i < j < N$)을 이중 반복문으로 확인합니다.
