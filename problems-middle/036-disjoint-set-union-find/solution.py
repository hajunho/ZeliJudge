import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    M = int(lines[1])
    idx = 2
    
    parent = list(range(N + 1))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
        
    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra
            
    out = []
    for _ in range(M):
        cmd = int(lines[idx])
        a = int(lines[idx+1])
        b = int(lines[idx+2])
        idx += 3
        if cmd == 0:
            union(a, b)
        else:
            if find(a) == find(b):
                out.append("YES")
            else:
                out.append("NO")
    print("\n".join(out))

if __name__ == "__main__":
    solve()
