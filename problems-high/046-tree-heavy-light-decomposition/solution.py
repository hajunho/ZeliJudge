import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    weights = [0] + [int(x) for x in input_data[2:2+n]]
    adj = [[] for _ in range(n + 1)]
    idx = 2 + n
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        adj[u].append(v)
        adj[v].append(u)
        
    sz = [0] * (n + 1)
    dep = [0] * (n + 1)
    parent = [0] * (n + 1)
    heavy = [0] * (n + 1)
    
    # 1. DFS for sizes and heavy children
    def dfs1(u, p, d):
        sz[u] = 1
        dep[u] = d
        parent[u] = p
        max_sz = 0
        for v in adj[u]:
            if v != p:
                dfs1(v, u, d + 1)
                sz[u] += sz[v]
                if sz[v] > max_sz:
                    max_sz = sz[v]
                    heavy[u] = v

    dfs1(1, 0, 0)
    
    head = [0] * (n + 1)
    pos = [0] * (n + 1)
    order = 0
    base_arr = [0] * n
    
    # 2. DFS for chain heads and positions
    def dfs2(u, h):
        nonlocal order
        head[u] = h
        pos[u] = order
        base_arr[order] = weights[u]
        order += 1
        
        if heavy[u] != 0:
            dfs2(heavy[u], h)
            for v in adj[u]:
                if v != parent[u] and v != heavy[u]:
                    dfs2(v, v)

    dfs2(1, 1)
    
    # Segment Tree
    tree = [0] * (4 * n)
    
    def build(node, s, e):
        if s == e:
            tree[node] = base_arr[s]
            return tree[node]
        mid = (s + e) // 2
        tree[node] = build(node * 2, s, mid) + build(node * 2 + 1, mid + 1, e)
        return tree[node]
        
    def update(node, s, e, target, val):
        if target < s or e < target:
            return
        if s == e:
            tree[node] = val
            return
        mid = (s + e) // 2
        update(node * 2, s, mid, target, val)
        update(node * 2 + 1, mid + 1, e, target, val)
        tree[node] = tree[node * 2] + tree[node * 2 + 1]
        
    def query(node, s, e, l, r):
        if r < s or e < l:
            return 0
        if l <= s and e <= r:
            return tree[node]
        mid = (s + e) // 2
        return query(node * 2, s, mid, l, r) + query(node * 2 + 1, mid + 1, e, l, r)

    build(1, 0, n - 1)
    
    def path_query(u, v):
        res = 0
        while head[u] != head[v]:
            if dep[head[u]] > dep[head[v]]:
                u, v = v, u
            res += query(1, 0, n - 1, pos[head[v]], pos[v])
            v = parent[head[v]]
        if dep[u] > dep[v]:
            u, v = v, u
        res += query(1, 0, n - 1, pos[u], pos[v])
        return res

    out = []
    for _ in range(m):
        qtype = int(input_data[idx])
        qa = int(input_data[idx+1])
        qb = int(input_data[idx+2])
        idx += 3
        if qtype == 1:
            update(1, 0, n - 1, pos[qa], qb)
        else:
            ans = path_query(qa, qb)
            out.append(str(ans))
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
