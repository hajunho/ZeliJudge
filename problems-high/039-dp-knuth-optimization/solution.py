import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    arr = [int(x) for x in input_data[1:1+n]]
    
    # 누적합
    pref = [0] * (n + 1)
    for i in range(1, n + 1):
        pref[i] = pref[i - 1] + arr[i - 1]
        
    dp = [[0] * n for _ in range(n)]
    opt = [[0] * n for _ in range(n)]
    
    for i in range(n):
        opt[i][i] = i
        
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            cost = pref[j + 1] - pref[i]
            
            min_val = float('inf')
            best_k = opt[i][j - 1]
            
            # 크누스 최적 분할 범위: opt[i][j-1] ~ opt[i+1][j]
            limit_r = opt[i + 1][j] if i + 1 <= j else j - 1
            for k in range(opt[i][j - 1], min(limit_r + 1, j)):
                val = dp[i][k] + dp[k + 1][j] + cost
                if val < min_val:
                    min_val = val
                    best_k = k
                    
            dp[i][j] = min_val
            opt[i][j] = best_k
            
    print(dp[0][n - 1])

if __name__ == "__main__":
    solve()
