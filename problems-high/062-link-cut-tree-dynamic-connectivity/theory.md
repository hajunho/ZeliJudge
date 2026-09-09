# 이론 및 해설: 트리를 자르고 붙이며 경로를 질의하라! 링크-컷 트리 (Link-Cut Tree)

### 링크-컷 트리 (Link-Cut Tree)

링크-컷 트리(LCT)는 트리의 동적 분할(Heavy-Light 같은 경로 분할)을 스플레이 트리(Splay Tree)로 관리하여 트리의 구조 변화(간선 추가/제거)와 경로 쿼리를 분할 상환 $O(\log N)$에 처리하는 강력한 자료구조입니다.

1. **기본 연산**:
   - `access(u)`: 루트에서 정점 $u$까지의 경로를 하나의 Prefered Path로 만들고, $u$를 해당 스플레이 트리의 가장 깊은 노드로 만듭니다.
   - `make_root(u)`: `access(u)` 후 `splay(u)`하여 트리의 루트를 $u$로 바꿉니다(방향 뒤집기 lazy tag 활용).
   - `link(u, v)`: $u$와 $v$ 사이에 간선을 추가합니다. `make_root(u)` 후 `u.parent = v`로 연결합니다.
   - `cut(u, v)`: $u$와 $v$ 사이의 간선을 제거합니다. `make_root(u)` 후 `access(v)`, `splay(v)`를 수행하면 $u$는 $v$의 왼쪽 자식이 되므로 자식 링크를 끊습니다.
   - `query(u, v)`: `make_root(u)` 후 `access(v)`, `splay(v)`하면 $v$를 루트로 하는 스플레이 트리에 $u$부터 $v$까지의 모든 경로 정점이 모이게 되므로 서브트리 집계 값(예: 최댓값)을 즉시 얻을 수 있습니다.
