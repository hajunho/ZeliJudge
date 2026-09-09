import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    edges = []
    idx = 2
    for _ in range(e):
        u = int(input_data[idx])
        node_v = int(input_data[idx+1])
        w = int(input_data[idx+2])
        idx += 3
        edges.append((w, u, node_v))
        
    edges.sort()
    
    parent = list(range(v + 1))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
        
    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra == rb:
            return False
        parent[rb] = ra
        return True
        
    total_weight = 0
    edges_count = 0
    
    for w, u, node_v in edges:
        if union(u, node_v):
            total_weight += w
            edges_count += 1
            if edges_count == v - 1:
                break
                
    print(total_weight)

if __name__ == "__main__":
    solve()
