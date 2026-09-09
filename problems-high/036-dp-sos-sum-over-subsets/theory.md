# SOS DP (Sum Over Subsets)

## 1. 3^N의 한계와 비트 분할
각 마스크의 모든 서브마스크를 순회하는 $O(3^N)$ 방식 대신, 비트 위치 $i$를 $0$부터 $N-1$까지 순차적으로 켜는 방식을 취합니다.

## 2. 2^N 점화식 원리
`dp[mask]`를 $A[mask]$로 초기화한 뒤:
```python
for i in range(N):
    for mask in range(1 << N):
        if mask & (1 << i):
            dp[mask] += dp[mask ^ (1 << i)]
```
$i$번째 비트가 1인 마스크는 $i$번째 비트가 0인 대응 마스크의 누적합을 그대로 더해 받으므로, 중복 없이 $O(N 2^N)$에 모든 부분집합 합이 구해집니다.