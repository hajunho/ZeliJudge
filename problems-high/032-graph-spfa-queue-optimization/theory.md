# SPFA (Shortest Path Faster Algorithm)

## 1. 큐 최적화 원리
- `in_queue[u]`: 정점 u가 현재 큐 안에 들어있는지 나타내는 플래그
- `count[u]`: 정점 u가 큐에 들어간 횟수
- `dist[v] > dist[u] + w`로 거리가 갱신되었을 때, `v`가 아직 큐에 없다면 큐에 삽입하고 `in_queue[v] = True`로 설정합니다.

## 2. 복잡도와 음수 사이클
- 최악의 경우 O(NM)이지만, 랜덤 그래프나 일반적인 그래프에서 평균 $O(E)$에 매우 빠르게 동작합니다.
- `count[v] >= N`이 되는 순간 음수 사이클로 즉시 중단합니다.