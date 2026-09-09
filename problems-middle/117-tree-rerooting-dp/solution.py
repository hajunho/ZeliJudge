import sys

# Increase recursion depth
sys.setrecursionlimit(200000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    
    adj = [[] for _ in range(N + 1)]
    idx = 1
    for _ in range(N - 1):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    sz = [0] * (N + 1)
    ans = [0] * (N + 1)
    
    # 1. First DFS: compute subtree sizes and ans[1]
    def dfs1(u, p, d):
        sz[u] = 1
        ans[1] += d
        for v in adj[u]:
            if v != p:
                dfs1(v, u, d + 1)
                sz[u] += sz[v]
                
    dfs1(1, 0, 0)
    
    # 2. Second DFS: Re-rooting
    # When root moves from u to v:
    # ans[v] = ans[u] - sz[v] + (N - sz[v])
    def dfs2(u, p):
        for v in adj[u]:
            if v != p:
                ans[v] = ans[u] - sz[v] + (N - sz[v])
                dfs2(v, u)
                
    dfs2(1, 0)
    
    print(' '.join(map(str, ans[1:N+1])))

if __name__ == "__main__":
    solve()
