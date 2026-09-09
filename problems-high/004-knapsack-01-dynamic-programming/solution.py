import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    max_w = int(input_data[1])
    
    dp = [0] * (max_w + 1)
    
    idx = 2
    for _ in range(n):
        w = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        
        for cur_w in range(max_w, w - 1, -1):
            if dp[cur_w - w] + v > dp[cur_w]:
                dp[cur_w] = dp[cur_w - w] + v
                
    print(dp[max_w])

if __name__ == "__main__":
    solve()
