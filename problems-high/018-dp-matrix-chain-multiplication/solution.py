import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    r = []
    c = []
    idx = 1
    for _ in range(n):
        r.append(int(input_data[idx]))
        c.append(int(input_data[idx+1]))
        idx += 2
        
    INF = float('inf')
    dp = [[0] * n for _ in range(n)]
    
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            dp[i][j] = INF
            for k in range(i, j):
                cost = dp[i][k] + dp[k+1][j] + r[i] * c[k] * c[j]
                if cost < dp[i][j]:
                    dp[i][j] = cost
                    
    print(dp[0][n-1])

if __name__ == "__main__":
    solve()
