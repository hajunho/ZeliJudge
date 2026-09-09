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
        
    LOG = 18
    up = [[0] * (N + 1) for _ in range(LOG)]
    depth = [0] * (N + 1)
    
    def dfs(u, p, d):
        depth[u] = d
        up[0][u] = p
        for v in adj[u]:
            if v != p:
                dfs(v, u, d + 1)
                
    dfs(1, 0, 1)
    
    for k in range(1, LOG):
        for u in range(1, N + 1):
            parent = up[k-1][u]
            up[k][u] = up[k-1][parent] if parent != 0 else 0
            
    def lca(u, v):
        if depth[u] < depth[v]:
            u, v = v, u
            
        # Lift u to the same depth as v
        diff = depth[u] - depth[v]
        for k in range(LOG - 1, -1, -1):
            if (diff >> k) & 1:
                u = up[k][u]
                
        if u == v:
            return u
            
        # Lift both until just below LCA
        for k in range(LOG - 1, -1, -1):
            if up[k][u] != up[k][v]:
                u = up[k][u]
                v = up[k][v]
                
        return up[0][u]
        
    out = []
    for _ in range(Q):
        u = int(lines[idx])
        v = int(lines[idx+1])
        idx += 2
        out.append(str(lca(u, v)))
        
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
