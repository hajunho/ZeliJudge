import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    arr = [int(x) for x in lines[1:1+N]]
    
    # Prefix sums
    pref = [0] * (N + 1)
    for i in range(N):
        pref[i+1] = pref[i] + arr[i]
        
    def cost(i, j):
        return pref[j+1] - pref[i]
        
    # dp[i][j]: min cost to merge files from i to j
    # opt[i][j]: optimal split index k
    dp = [[0] * N for _ in range(N)]
    opt = [[0] * N for _ in range(N)]
    
    for i in range(N):
        opt[i][i] = i
        
    for length in range(2, N + 1):
        for i in range(N - length + 1):
            j = i + length - 1
            dp[i][j] = 10**18
            c = cost(i, j)
            
            # Knuth optimization: opt[i][j-1] <= opt[i][j] <= opt[i+1][j]
            k_start = opt[i][j-1]
            k_end = opt[i+1][j] if i + 1 <= j else j - 1
            
            for k in range(k_start, min(k_end + 1, j)):
                val = dp[i][k] + dp[k+1][j] + c
                if val < dp[i][j]:
                    dp[i][j] = val
                    opt[i][j] = k
                    
    print(dp[0][N-1])

if __name__ == "__main__":
    solve()
