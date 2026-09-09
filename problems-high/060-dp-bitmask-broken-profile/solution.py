import sys

MOD = 1000000007

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    if (n * m) % 2 != 0:
        print(0)
        return
        
    if n < m:
        n, m = m, n
        
    dp = [0] * (1 << m)
    dp[0] = 1
    
    for r in range(n):
        for c in range(m):
            next_dp = [0] * (1 << m)
            for mask in range(1 << m):
                if dp[mask] == 0:
                    continue
                if mask & (1 << c):
                    # 이미 위쪽에서 세로로 채워져 내려옴 -> 도미노 안 놓고 비트 끔
                    next_dp[mask ^ (1 << c)] = (next_dp[mask ^ (1 << c)] + dp[mask]) % MOD
                else:
                    # 1. 세로 도미노 놓기: (r, c)와 (r+1, c)를 덮음 -> 비트 켬
                    if r + 1 < n:
                        next_dp[mask | (1 << c)] = (next_dp[mask | (1 << c)] + dp[mask]) % MOD
                    # 2. 가로 도미노 놓기: (r, c)와 (r, c+1)를 덮음 -> c+1이 비어있어야 함
                    if c + 1 < m and not (mask & (1 << (c + 1))):
                        next_dp[mask | (1 << (c + 1))] = (next_dp[mask | (1 << (c + 1))] + dp[mask]) % MOD
            dp = next_dp
            
    print(dp[0])

if __name__ == "__main__":
    solve()
