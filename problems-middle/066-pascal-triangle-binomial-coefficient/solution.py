import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    K = int(lines[1])
    MOD = 1000000007
    
    dp = [[0] * (K + 1) for _ in range(N + 1)]
    for i in range(N + 1):
        dp[i][0] = 1
        for j in range(1, min(i, K) + 1):
            dp[i][j] = (dp[i-1][j-1] + dp[i-1][j]) % MOD
            
    print(dp[N][K])

if __name__ == "__main__":
    solve()
