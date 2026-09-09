# 플로이드-워셜(Floyd-Warshall) 알고리즘

## 1. 개념 및 점화식
그래프의 모든 정점 쌍 (i, j) 사이의 최단 거리를 구하는 $O(V^3)$ 동적 계획법 알고리즘입니다.
핵심 아이디어: '정점 1번부터 k번까지를 경유지로 고려했을 때'의 최단 거리를 점진적으로 확장합니다.

$$\text{dist}[i][j] = \min(\text{dist}[i][j], \text{dist}[i][k] + \text{dist}[k][j])$$

## 2. 구현 시 주의점
반드시 **경유지 k 루프가 가장 바깥쪽**에 위치해야 합니다:
```python
for k in range(1, n + 1):       # 경유지
    for i in range(1, n + 1):   # 출발지
        for j in range(1, n + 1): # 도착지
            dist[i][j] = min(dist[i][j], dist[i][k] + dist[k][j])
```
V가 100~500 이하인 문제에서 전쌍 최단 거리를 가장 간결하게 구현할 수 있습니다.