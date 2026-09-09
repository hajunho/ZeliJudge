import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    idx = 1
    w = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            w[i][j] = int(input_data[idx])
            idx += 1
            
    dp = [[float('inf')] * n for _ in range(1 << n)]
    dp[1][0] = 0
    
    for mask in range(1, 1 << n):
        for u in range(n):
            if dp[mask][u] == float('inf'):
                continue
            for v in range(n):
                if not (mask & (1 << v)):
                    nxt_mask = mask | (1 << v)
                    cost = dp[mask][u] + w[u][v]
                    if cost < dp[nxt_mask][v]:
                        dp[nxt_mask][v] = cost
                        
    ans = float('inf')
    full = (1 << n) - 1
    for u in range(1, n):
        ans = min(ans, dp[full][u] + w[u][0])
        
    print(ans)

if __name__ == '__main__':
    solve()
