import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k = int(input_data[1])
    prices = [int(x) for x in input_data[2:2+n]]
    
    if n <= 1 or k == 0:
        print(0)
        return
        
    # If k >= n // 2, simple greedy
    if k >= n // 2:
        ans = 0
        for i in range(1, n):
            if prices[i] > prices[i - 1]:
                ans += prices[i] - prices[i - 1]
        print(ans)
        return
        
    # Aliens trick: binary search penalty lambda for each transaction
    def check(penalty):
        # dp[0]: not holding stock (val, cnt)
        # dp[1]: holding stock (val, cnt)
        dp0_val, dp0_cnt = 0, 0
        dp1_val, dp1_cnt = -prices[0] - penalty, 1
        
        for p in prices[1:]:
            # Sell transition: buy at dp1, sell at p
            sell_val = dp1_val + p
            sell_cnt = dp1_cnt
            if sell_val > dp0_val or (sell_val == dp0_val and sell_cnt < dp0_cnt):
                new_dp0_val, new_dp0_cnt = sell_val, sell_cnt
            else:
                new_dp0_val, new_dp0_cnt = dp0_val, dp0_cnt
                
            # Buy transition: start new transaction with penalty
            buy_val = dp0_val - p - penalty
            buy_cnt = dp0_cnt + 1
            if buy_val > dp1_val or (buy_val == dp1_val and buy_cnt < dp1_cnt):
                new_dp1_val, new_dp1_cnt = buy_val, buy_cnt
            else:
                new_dp1_val, new_dp1_cnt = dp1_val, dp1_cnt
                
            dp0_val, dp0_cnt = new_dp0_val, new_dp0_cnt
            dp1_val, dp1_cnt = new_dp1_val, new_dp1_cnt
            
        return dp0_val, dp0_cnt

    low = 0
    high = 10**9
    best_ans = 0
    
    for _ in range(60):
        mid = (low + high) // 2
        val, cnt = check(mid)
        if cnt <= k:
            best_ans = val + mid * k
            high = mid
        else:
            low = mid + 1
            
    val, cnt = check(low)
    ans = val + low * k
    print(max(0, ans))

if __name__ == '__main__':
    solve()
