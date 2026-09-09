import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    arr = [int(x) for x in lines[1:N+1]]
    
    dp = [1] * N
    for i in range(N):
        for j in range(i):
            if arr[j] < arr[i]:
                if dp[j] + 1 > dp[i]:
                    dp[i] = dp[j] + 1
                    
    print(max(dp))

if __name__ == "__main__":
    solve()
