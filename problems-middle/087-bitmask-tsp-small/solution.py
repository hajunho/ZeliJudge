import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    W = []
    for _ in range(N):
        row = [int(x) for x in lines[idx:idx+N]]
        W.append(row)
        idx += N
        
    INF = 10**18
    # dp[mask][u]: min cost visited mask ending at u
    dp = [[INF] * N for _ in range(1 << N)]
    
    # Base case: start at city 0
    dp[1][0] = 0
    
    for mask in range(1, 1 << N):
        for u in range(N):
            if dp[mask][u] == INF:
                continue
            for v in range(N):
                if not ((mask >> v) & 1) and W[u][v] > 0:
                    next_mask = mask | (1 << v)
                    if dp[mask][u] + W[u][v] < dp[next_mask][v]:
                        dp[next_mask][v] = dp[mask][u] + W[u][v]
                        
    ans = INF
    full_mask = (1 << N) - 1
    for u in range(1, N):
        if dp[full_mask][u] != INF and W[u][0] > 0:
            ans = min(ans, dp[full_mask][u] + W[u][0])
            
    if ans == INF:
        print("-1")
    else:
        print(ans)

if __name__ == "__main__":
    solve()
