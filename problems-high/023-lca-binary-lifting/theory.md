# 이진 리프팅 (Binary Lifting) LCA

## 1. 희소 배열 (Sparse Table) 구축
- `parent[k][node]`: `node`의 $2^k$번째 조상 노드 번호
- 점화식: `parent[k][node] = parent[k-1][parent[k-1][node]]`
- $O(N \log N)$ 시간에 전체 테이블을 전처리합니다.

## 2. 쿼리 처리 절차 ($O(\log N)$)
1. 두 노드의 깊이(`depth`)가 같아지도록 더 깊은 노드를 $2^k$씩 점프시켜 끌어올립니다.
2. 두 노드가 같아졌다면 그 노드가 바로 LCA입니다.
3. 두 노드의 부모가 달라지지 않는 가장 큰 $2^k$만큼 두 노드를 동시에 위로 점프시킵니다.
4. 최종적으로 두 노드의 바로 윗 부모(`parent[0][u]`)가 LCA가 됩니다.