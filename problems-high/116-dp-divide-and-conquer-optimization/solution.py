import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k_part = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    pref = [0] * (n + 1)
    for i in range(1, n + 1):
        pref[i] = pref[i - 1] + arr[i - 1]
        
    def cost(j, i):
        s = pref[i] - pref[j]
        return s * s
        
    dp_prev = [cost(0, i) for i in range(n + 1)]
    dp_cur = [0] * (n + 1)
    
    def compute(l, r, opt_l, opt_r):
        if l > r:
            return
        mid = (l + r) // 2
        best_val = float('inf')
        best_opt = -1
        
        limit = min(mid - 1, opt_r)
        for j in range(opt_l, limit + 1):
            val = dp_prev[j] + cost(j, mid)
            if val < best_val:
                best_val = val
                best_opt = j
                
        dp_cur[mid] = best_val
        compute(l, mid - 1, opt_l, best_opt)
        compute(mid + 1, r, best_opt, opt_r)

    for _ in range(2, k_part + 1):
        compute(1, n, 0, n - 1)
        dp_prev, dp_cur = dp_cur, [0] * (n + 1)
        
    print(dp_prev[n])

if __name__ == '__main__':
    solve()
