import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    weights = [0] + [int(x) for x in input_data[1:1+n]]
    
    adj = [[] for _ in range(n + 1)]
    idx = 1 + n
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        adj[u].append(v)
        adj[v].append(u)
        
    dp = [[0, 0] for _ in range(n + 1)]
    visited = [False] * (n + 1)
    
    def dfs(u):
        visited[u] = True
        dp[u][0] = 0
        dp[u][1] = weights[u]
        
        for v in adj[u]:
            if not visited[v]:
                dfs(v)
                dp[u][0] += max(dp[v][0], dp[v][1])
                dp[u][1] += dp[v][0]

    dfs(1)
    print(max(dp[1][0], dp[1][1]))

if __name__ == "__main__":
    solve()
