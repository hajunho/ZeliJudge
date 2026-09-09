import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    S1 = lines[0]
    S2 = lines[1]
    
    n = len(S1)
    m = len(S2)
    
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    max_len = 0
    end_idx = 0 # end index in S1
    
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if S1[i-1] == S2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
                if dp[i][j] > max_len:
                    max_len = dp[i][j]
                    end_idx = i
            else:
                dp[i][j] = 0
                
    print(max_len)
    if max_len > 0:
        print(S1[end_idx - max_len:end_idx])

if __name__ == "__main__":
    solve()
