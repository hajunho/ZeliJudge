import sys
sys.setrecursionlimit(20000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k_groups = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    pref = [0] * (n + 1)
    for i in range(1, n + 1):
        pref[i] = pref[i - 1] + arr[i - 1]
        
    def cost(l, r):
        s = pref[r] - pref[l - 1]
        return s * s
        
    INF = 10**18
    dp = [INF] * (n + 1)
    dp[0] = 0
    for i in range(1, n + 1):
        dp[i] = cost(1, i)
        
    new_dp = [INF] * (n + 1)
    
    def compute(l, r, opt_l, opt_r):
        if l > r:
            return
        mid = (l + r) // 2
        best_val = INF
        best_opt = opt_l
        
        for j in range(opt_l, min(mid, opt_r + 1)):
            val = dp[j] + cost(j + 1, mid)
            if val < best_val:
                best_val = val
                best_opt = j
                
        new_dp[mid] = best_val
        compute(l, mid - 1, opt_l, best_opt)
        compute(mid + 1, r, best_opt, opt_r)

    for k in range(2, k_groups + 1):
        new_dp = [INF] * (n + 1)
        compute(k, n, k - 1, n)
        dp = new_dp[:]
        
    print(dp[n])

if __name__ == "__main__":
    solve()
