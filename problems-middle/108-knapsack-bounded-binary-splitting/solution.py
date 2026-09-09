import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    W = int(lines[1])
    
    idx = 2
    items = [] # (weight, value)
    for _ in range(N):
        w = int(lines[idx])
        v = int(lines[idx+1])
        k = int(lines[idx+2])
        idx += 3
        
        # Binary splitting of count k
        p = 1
        while p <= k:
            items.append((w * p, v * p))
            k -= p
            p <<= 1
        if k > 0:
            items.append((w * k, v * k))
            
    # 0-1 Knapsack DP
    dp = [0] * (W + 1)
    for weight, value in items:
        for cap in range(W, weight - 1, -1):
            if dp[cap - weight] + value > dp[cap]:
                dp[cap] = dp[cap - weight] + value
                
    print(dp[W])

if __name__ == "__main__":
    solve()
