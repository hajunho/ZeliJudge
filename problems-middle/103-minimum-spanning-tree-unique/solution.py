import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    
    edges = []
    idx = 2
    for i in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        edges.append((w, u, v, i))
        idx += 3
        
    edges.sort(key=lambda x: x[0])
    
    def get_mst(skip_idx=-1):
        parent = list(range(V + 1))
        def find(x):
            if parent[x] == x:
                return x
            parent[x] = find(parent[x])
            return parent[x]
            
        def union(x, y):
            rx = find(x)
            ry = find(y)
            if rx == ry:
                return False
            parent[rx] = ry
            return True
            
        mst_weight = 0
        used_edges = []
        for w, u, v, eid in edges:
            if eid == skip_idx:
                continue
            if union(u, v):
                mst_weight += w
                used_edges.append(eid)
                if len(used_edges) == V - 1:
                    break
                    
        if len(used_edges) == V - 1:
            return mst_weight, used_edges
        return None, []
        
    base_weight, mst_edges = get_mst()
    if base_weight is None:
        print("NO")
        return
        
    # Check if there is another MST with same base_weight
    is_unique = True
    for edge_to_skip in mst_edges:
        alt_weight, _ = get_mst(edge_to_skip)
        if alt_weight is not None and alt_weight == base_weight:
            is_unique = False
            break
            
    print(base_weight)
    if is_unique:
        print("UNIQUE")
    else:
        print("NOT UNIQUE")

if __name__ == "__main__":
    solve()
