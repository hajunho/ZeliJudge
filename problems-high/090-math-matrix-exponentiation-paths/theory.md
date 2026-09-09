# 이론 및 해설: 길이 K의 경로를 거듭제곱으로 세다! 행렬 지수승 (Matrix Exponentiation)

### 행렬 거듭제곱과 경로 수 (Matrix Exponentiation)

인접 행렬 $A$에 대해 $A^K[i][j]$는 정점 $i$에서 $j$로 가는 길이가 정확히 $K$인 경로의 수입니다. 분할 정복 거듭제곱으로 $O(V^3 \log K)$에 계산합니다.
