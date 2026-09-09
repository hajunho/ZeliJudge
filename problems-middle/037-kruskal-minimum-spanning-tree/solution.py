import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    idx = 2
    edges = []
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        edges.append((w, u, v))
        idx += 3
        
    edges.sort()
    parent = list(range(V + 1))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
        
    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra
            return True
        return False
        
    total_cost = 0
    edge_count = 0
    for w, u, v in edges:
        if union(u, v):
            total_cost += w
            edge_count += 1
            if edge_count == V - 1:
                break
                
    if V == 1:
        print(0)
    elif edge_count == V - 1:
        print(total_cost)
    else:
        print(-1)

if __name__ == "__main__":
    solve()
