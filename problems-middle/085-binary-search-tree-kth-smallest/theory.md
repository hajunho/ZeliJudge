# 이진 검색 트리(BST)와 중위 순회(In-Order Traversal)

### 1. BST의 대소 규칙과 중위 순회
이진 검색 트리의 모든 노드 $X$에 대해:
$$\text{Left Subtree Keys} < X.val < \text{Right Subtree Keys}$$
성질이 항상 성립합니다.
따라서 `Left -> Root -> Right` 순서로 방문하는 중위 순회(In-order)를 수행하면, 별도의 정렬 알고리즘 없이도 **자동으로 완벽한 오름차순 수열**을 얻게 됩니다!

### 2. K번째 원소 탐색
중위 순회 중에 방문한 노드의 카운트가 $K$에 도달하는 순간의 노드 값이 곧 $K$번째 최솟값입니다.
균형 잡힌 트리라면 삽입과 탐색 모두 $O(\log N)$에 수행됩니다.
