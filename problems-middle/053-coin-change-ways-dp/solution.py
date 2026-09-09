import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    K = int(lines[1])
    idx = 2
    coins = [int(lines[idx + i]) for i in range(N)]
    
    MOD = 1000000007
    dp = [0] * (K + 1)
    dp[0] = 1
    
    for c in coins:
        for x in range(c, K + 1):
            dp[x] = (dp[x] + dp[x - c]) % MOD
            
    print(dp[K])

if __name__ == "__main__":
    solve()
