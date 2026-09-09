import sys

# Set recursion depth
sys.setrecursionlimit(100000)

class Node:
    def __init__(self, val):
        self.val = val
        self.left = None
        self.right = None

def insert(root, val):
    if root is None:
        return Node(val)
    if val < root.val:
        root.left = insert(root.left, val)
    else:
        root.right = insert(root.right, val)
    return root

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    K = int(lines[1])
    vals = [int(x) for x in lines[2:2+N]]
    
    root = None
    for v in vals:
        root = insert(root, v)
        
    inorder_list = []
    def inorder(node):
        if node is None:
            return
        inorder(node.left)
        inorder_list.append(node.val)
        inorder(node.right)
        
    inorder(root)
    
    print(' '.join(map(str, inorder_list)))
    print(inorder_list[K - 1])

if __name__ == "__main__":
    solve()
