import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    # N matrices: dims has size N+1
    # Matrix i has size dims[i-1] x dims[i]
    # Input has N lines of (r, c)
    r_list = []
    c_list = []
    for _ in range(N):
        r_list.append(int(lines[idx]))
        c_list.append(int(lines[idx+1]))
        idx += 2
        
    p = [r_list[0]] + c_list
    
    # dp[i][j]: min ops to multiply matrices from i to j (0-based)
    dp = [[0] * N for _ in range(N)]
    
    for length in range(2, N + 1):
        for i in range(N - length + 1):
            j = i + length - 1
            dp[i][j] = 10**18
            for k in range(i, j):
                cost = dp[i][k] + dp[k+1][j] + p[i] * p[k+1] * p[j+1]
                if cost < dp[i][j]:
                    dp[i][j] = cost
                    
    print(dp[0][N-1])

if __name__ == "__main__":
    solve()
