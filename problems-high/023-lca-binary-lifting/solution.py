import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    adj = [[] for _ in range(n + 1)]
    idx = 1
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        adj[u].append(v)
        adj[v].append(u)
        
    MAX_K = 18
    parent = [[0] * (n + 1) for _ in range(MAX_K)]
    depth = [-1] * (n + 1)
    
    def dfs(cur, d):
        depth[cur] = d
        for nxt in adj[cur]:
            if depth[nxt] == -1:
                parent[0][nxt] = cur
                dfs(nxt, d + 1)

    dfs(1, 0)
    
    for k in range(1, MAX_K):
        for node in range(1, n + 1):
            parent[k][node] = parent[k-1][parent[k-1][node]]
            
    def lca(a, b):
        if depth[a] < depth[b]:
            a, b = b, a
            
        diff = depth[a] - depth[b]
        for k in range(MAX_K):
            if diff & (1 << k):
                a = parent[k][a]
                
        if a == b:
            return a
            
        for k in range(MAX_K - 1, -1, -1):
            if parent[k][a] != parent[k][b]:
                a = parent[k][a]
                b = parent[k][b]
                
        return parent[0][a]

    m = int(input_data[idx])
    idx += 1
    out = []
    for _ in range(m):
        qa = int(input_data[idx])
        qb = int(input_data[idx+1])
        idx += 2
        out.append(str(lca(qa, qb)))
        
    print("\n".join(out))

if __name__ == "__main__":
    solve()
