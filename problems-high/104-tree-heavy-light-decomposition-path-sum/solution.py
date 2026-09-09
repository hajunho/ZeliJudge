import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    weights = [0] + [int(x) for x in input_data[1:1+n]]
    idx = 1 + n
    
    adj = [[] for _ in range(n + 1)]
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        adj[u].append(v)
        adj[v].append(u)
        
    parent = [0] * (n + 1)
    depth = [0] * (n + 1)
    sz = [0] * (n + 1)
    heavy = [0] * (n + 1)
    
    # DFS 1: size, heavy child
    stack = [(1, 0, 0)]
    order = []
    visited = [False] * (n + 1)
    visited[1] = True
    
    # Iterative traversal for tree properties
    q = [1]
    head = 0
    parent[1] = 0
    depth[1] = 0
    bfs_order = []
    while head < len(q):
        u = q[head]
        head += 1
        bfs_order.append(u)
        for v in adj[u]:
            if v != parent[u]:
                parent[v] = u
                depth[v] = depth[u] + 1
                q.append(v)
                
    for u in reversed(bfs_order):
        sz[u] = 1
        max_c = 0
        for v in adj[u]:
            if v != parent[u]:
                sz[u] += sz[v]
                if sz[v] > max_c:
                    max_c = sz[v]
                    heavy[u] = v
                    
    # DFS 2: chain head, in-order numbering
    head_chain = [0] * (n + 1)
    pos = [0] * (n + 1)
    cur_pos = 1
    
    # We can decompose using a queue/stack
    stack = [(1, 1)]
    while stack:
        u, h = stack.pop()
        head_chain[u] = h
        pos[u] = cur_pos
        cur_pos += 1
        # Push non-heavy children first so heavy child is popped first
        # (to maintain contiguous intervals for heavy chain)
        for v in adj[u]:
            if v != parent[u] and v != heavy[u]:
                stack.append((v, v))
        if heavy[u] != 0:
            stack.append((heavy[u], h))
            
    # Segment Tree over pos [1..n]
    tree = [0] * (4 * n + 4)
    
    def build(node, l, r):
        if l == r:
            # find which node has pos == l
            # we can store rev_pos
            return
        mid = (l + r) // 2
        build(node * 2, l, mid)
        build(node * 2 + 1, mid + 1, r)
        tree[node] = tree[node * 2] + tree[node * 2 + 1]
        
    rev_pos = [0] * (n + 1)
    for i in range(1, n + 1):
        rev_pos[pos[i]] = i
        
    def seg_build(node, l, r):
        if l == r:
            tree[node] = weights[rev_pos[l]]
            return
        mid = (l + r) // 2
        seg_build(node * 2, l, mid)
        seg_build(node * 2 + 1, mid + 1, r)
        tree[node] = tree[node * 2] + tree[node * 2 + 1]
        
    seg_build(1, 1, n)
    
    def seg_update(node, l, r, p, val):
        if l == r:
            tree[node] = val
            return
        mid = (l + r) // 2
        if p <= mid:
            seg_update(node * 2, l, mid, p, val)
        else:
            seg_update(node * 2 + 1, mid + 1, r, p, val)
        tree[node] = tree[node * 2] + tree[node * 2 + 1]
        
    def seg_query(node, l, r, ql, qr):
        if ql <= l and r <= qr:
            return tree[node]
        mid = (l + r) // 2
        res = 0
        if ql <= mid:
            res += seg_query(node * 2, l, mid, ql, qr)
        if qr > mid:
            res += seg_query(node * 2 + 1, mid + 1, r, ql, qr)
        return res
        
    def query_path(u, v):
        res = 0
        while head_chain[u] != head_chain[v]:
            if depth[head_chain[u]] < depth[head_chain[v]]:
                u, v = v, u
            res += seg_query(1, 1, n, pos[head_chain[u]], pos[u])
            u = parent[head_chain[u]]
        if depth[u] > depth[v]:
            u, v = v, u
        res += seg_query(1, 1, n, pos[u], pos[v])
        return res
        
    q_num = int(input_data[idx])
    idx += 1
    out = []
    for _ in range(q_num):
        t = int(input_data[idx])
        u = int(input_data[idx+1])
        v = int(input_data[idx+2])
        idx += 3
        if t == 1:
            seg_update(1, 1, n, pos[u], v)
        else:
            out.append(str(query_path(u, v)))
            
    print("\n".join(out))

if __name__ == '__main__':
    solve()
