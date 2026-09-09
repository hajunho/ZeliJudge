import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    S = lines[0]
    N = len(S)
    
    # dp[i][j]: length of LPS in S[i..j]
    dp = [[0] * N for _ in range(N)]
    
    for i in range(N):
        dp[i][i] = 1
        
    for length in range(2, N + 1):
        for i in range(N - length + 1):
            j = i + length - 1
            if S[i] == S[j]:
                dp[i][j] = dp[i+1][j-1] + 2 if length > 2 else 2
            else:
                dp[i][j] = max(dp[i+1][j], dp[i][j-1])
                
    print(dp[0][N-1])

if __name__ == "__main__":
    solve()
