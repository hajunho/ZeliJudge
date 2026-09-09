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
    def preorder(curr):
        if curr == 0:
            return
        order.append(curr)
        left, right = tree[curr]
        preorder(left)
        preorder(right)
        
    preorder(1)
    print(" ".join(map(str, order)))

if __name__ == "__main__":
    main()
