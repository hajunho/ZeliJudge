import sys

class Node:
    def __init__(self, key):
        self.key = key
        self.left = None
        self.right = None

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    vals = [int(lines[idx + i]) for i in range(N)]
    idx += N
    X = int(lines[idx])
    
    root = None
    for v in vals:
        if root is None:
            root = Node(v)
        else:
            curr = root
            while True:
                if v < curr.key:
                    if curr.left is None:
                        curr.left = Node(v)
                        break
                    curr = curr.left
                elif v > curr.key:
                    if curr.right is None:
                        curr.right = Node(v)
                        break
                    curr = curr.right
                else:
                    break
                    
    path = []
    curr = root
    found = False
    while curr:
        path.append(str(curr.key))
        if curr.key == X:
            found = True
            break
        elif X < curr.key:
            curr = curr.left
        else:
            curr = curr.right
            
    if found:
        print(" ".join(path))
    else:
        print(-1)

if __name__ == "__main__":
    solve()
