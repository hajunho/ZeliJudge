import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    size = 1 << n
    dp = [int(x) for x in input_data[1:1+size]]
    
    for i in range(n):
        bit = 1 << i
        for mask in range(size):
            if mask & bit:
                dp[mask] += dp[mask ^ bit]
                
    print(*(dp))

if __name__ == "__main__":
    solve()
