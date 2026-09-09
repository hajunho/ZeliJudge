# 쾨닉의 정리 (König's Theorem)와 최소 버텍스 커버

### 1. 최소 버텍스 커버 (Minimum Vertex Cover)
그래프의 모든 간선 $e = (u, v)$에 대해 적어도 $u$ 또는 $v$가 포함되도록 선택한 정점 집합 중 크기가 최소인 것을 말합니다.

### 2. 쾨닉의 정리 (Dénes Kőnig, 1931)
> **임의의 이분 그래프에서, 최대 매칭(Maximum Matching)의 간선 수는 최소 버텍스 커버(Minimum Vertex Cover)의 정점 수와 정확히 일치한다.**

- **증명 개요**: 최대 매칭의 각 간선은 서로 정점을 공유하지 않으므로, 이들을 커버하려면 적어도 매칭 수만큼의 정점이 필요합니다($\text{Cover} \ge \text{Matching}$).  
  반대로 교대 경로(Alternating Path)를 이용해 매칭 수와 정확히 같은 크기의 커버를 항상 구성할 수 있습니다.
- 따라서 DFS 증가 경로(Augmenting Path) 알고리즘으로 최대 이분 매칭을 구하면 최소 커버 크기가 즉시 도출됩니다.
