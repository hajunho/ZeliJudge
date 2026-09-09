import sys

# Increase recursion depth
sys.setrecursionlimit(200000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    Q = int(lines[1])
    
    adj = [[] for _ in range(N + 1)]
    idx = 2
    for _ in range(N - 1):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    parent = [0] * (N + 1)
    depth = [0] * (N + 1)
    sz = [0] * (N + 1)
    heavy = [0] * (N + 1)
    head = [0] * (N + 1)
    
    # DFS 1: parent, depth, subtree size, heavy edge
    def dfs1(u, p, d):
        parent[u] = p
        depth[u] = d
        sz[u] = 1
        max_c = 0
        for v in adj[u]:
            if v != p:
                dfs1(v, u, d + 1)
                sz[u] += sz[v]
                if sz[v] > max_c:
                    max_c = sz[v]
                    heavy[u] = v
                    
    dfs1(1, 0, 1)
    
    # DFS 2: HLD chain head
    def dfs2(u, h):
        head[u] = h
        if heavy[u] != 0:
            dfs2(heavy[u], h)
        for v in adj[u]:
            if v != parent[u] and v != heavy[u]:
                dfs2(v, v)
                
    dfs2(1, 1)
    
    def hld_lca(u, v):
        while head[u] != head[v]:
            if depth[head[u]] > depth[head[v]]:
                u = parent[head[u]]
            else:
                v = parent[head[v]]
        return u if depth[u] < depth[v] else v
        
    out = []
    for _ in range(Q):
        u = int(lines[idx])
        v = int(lines[idx+1])
        idx += 2
        out.append(str(hld_lca(u, v)))
        
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
