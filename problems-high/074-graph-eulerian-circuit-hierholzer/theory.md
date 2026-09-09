# 이론 및 해설: 모든 길을 단 한 번씩만 지나라! 오일러 회로 (Hierholzer's Algorithm)

### 오일러 회로 (Eulerian Circuit / Hierholzer's Algorithm)

방향 그래프에서 모든 간선을 정확히 한 번씩 거쳐 시작 정점으로 되돌아오는 경로를 오일러 회로(Eulerian Circuit)라고 합니다.

1. **존재 조건**:
   - 모든 정점 $v$에 대해 $\text{in-degree}(v) = \text{out-degree}(v)$.
   - 간선이 존재하는 모든 정점들이 하나의 약한 연결 컴포넌트에 속해야 합니다.
2. **히어홀저 알고리즘 ($O(V + E)$)**:
   - DFS로 간선을 지날 때마다 즉시 제거하고 막다른 정점에 도달하면 스택에 추가한 후 역순으로 회로를 복원합니다.
