import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    W = int(lines[1])
    idx = 2
    
    dp = [0] * (W + 1)
    for _ in range(N):
        w = int(lines[idx])
        v = int(lines[idx+1])
        idx += 2
        for cap in range(W, w - 1, -1):
            if dp[cap - w] + v > dp[cap]:
                dp[cap] = dp[cap - w] + v
                
    print(dp[W])

if __name__ == "__main__":
    solve()
