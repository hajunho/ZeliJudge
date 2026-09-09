import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    tree = {}
    for i in range(1, 1 + n):
        parts = lines[i].split()
        node = int(parts[0])
        left = int(parts[1])
        right = int(parts[2])
        tree[node] = (left, right)
        
    order = []
    def inorder(curr):
        if curr == 0:
            return
        left, right = tree[curr]
        inorder(left)
        order.append(curr)
        inorder(right)
        
    inorder(1)
    print(" ".join(map(str, order)))

if __name__ == "__main__":
    main()
