import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    s1 = lines[0]
    s2 = lines[1] if len(lines) > 1 else ""
    
    n = len(s1)
    m = len(s2)
    
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    
    for i in range(1, n + 1):
        c1 = s1[i-1]
        for j in range(1, m + 1):
            if c1 == s2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = dp[i-1][j] if dp[i-1][j] > dp[i][j-1] else dp[i][j-1]
                
    lcs_len = dp[n][m]
    print(lcs_len)
    
    if lcs_len > 0:
        res = []
        i, j = n, m
        while i > 0 and j > 0:
            if s1[i-1] == s2[j-1]:
                res.append(s1[i-1])
                i -= 1
                j -= 1
            elif dp[i-1][j] >= dp[i][j-1]:
                i -= 1
            else:
                j -= 1
        print("".join(reversed(res)))

if __name__ == "__main__":
    solve()
