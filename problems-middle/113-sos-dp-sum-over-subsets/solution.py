import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    size = 1 << N
    A = [int(x) for x in lines[1:1+size]]
    
    # SOS DP
    # dp[i][mask]: sum over submask of mask agreeing with mask on bits > i
    # Memory optimized to 1D
    dp = list(A)
    for i in range(N):
        bit = 1 << i
        for mask in range(size):
            if mask & bit:
                dp[mask] += dp[mask ^ bit]
                
    print(' '.join(map(str, dp)))

if __name__ == "__main__":
    solve()
