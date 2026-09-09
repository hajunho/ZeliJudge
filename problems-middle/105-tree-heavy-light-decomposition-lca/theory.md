# Heavy-Light Decomposition (HLD) 기반 LCA

### 1. Heavy Edge와 Light Edge의 분할
각 노드 $u$의 자식들 중 서브트리 크기 $sz[v]$가 최대인 자식을 Heavy Child로 선정합니다.
루트부터 Heavy Child를 따라 이어지는 경로를 하나의 **Heavy Chain**으로 묶습니다.
- 어떤 정점에서 부모로 이동할 때 Light Edge를 건널 때마다 서브트리의 크기가 최소 2배 이상 커지므로, 루트까지 Light Edge는 기껏해야 $\log_2 N$개만 존재합니다.

### 2. HLD LCA의 점프 원리
두 노드 $u, v$의 체인 머리 `head[u]`와 `head[v]`가 다르면:
- `depth[head[u]]`가 더 깊은 쪽 노드를 `parent[head[u]]`로 한 번에 점프시킵니다!
- 두 노드가 마침내 같은 체인에 도달하면, 깊이가 더 얕은 노드가 바로 LCA입니다.
최대 $\log N$번의 점프만으로 $O(\log N)$에 LCA를 구합니다.
