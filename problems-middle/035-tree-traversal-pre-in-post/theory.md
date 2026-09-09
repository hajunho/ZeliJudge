# 이진 트리의 3대 순회 알고리즘

### 1. 순회의 기준: 루트(Root)의 방문 타이밍
모든 순회는 항상 **왼쪽 서브트리를 오른쪽 서브트리보다 먼저** 방문합니다.  
차이점은 오직 **현재 노드(루트)를 앞/중간/뒤 중 언제 처리하느냐**뿐입니다:

| 순회 방식 | 방문 순서 | 주 활용 분야 |
|---|---|---|
| **전위 순회 (Pre-order)** | **루트** $\to$ 왼쪽 $\to$ 오른쪽 | 트리 복제, 직렬화(Serialization) |
| **중위 순회 (In-order)** | 왼쪽 $\to$ **루트** $\to$ 오른쪽 | 이진 탐색 트리(BST) 정렬 출력 |
| **후위 순회 (Post-order)** | 왼쪽 $\to$ 오른쪽 $\to$ **루트** | 트리 삭제(자식 먼저 삭제), 디렉터리 용량 합산 |

---

### 2. 재귀를 이용한 간결한 구현
```python
def preorder(node):
    if node is None: return
    visit(node)           # 1. 루트 처리
    preorder(node.left)   # 2. 왼쪽 서브트리
    preorder(node.right)  # 3. 오른쪽 서브트리

def inorder(node):
    if node is None: return
    inorder(node.left)    # 1. 왼쪽 서브트리
    visit(node)           # 2. 루트 처리
    inorder(node.right)   # 3. 오른쪽 서브트리

def postorder(node):
    if node is None: return
    postorder(node.left)  # 1. 왼쪽 서브트리
    postorder(node.right) # 2. 오른쪽 서브트리
    visit(node)           # 3. 루트 처리
```
