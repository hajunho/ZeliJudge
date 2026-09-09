import sys
from collections import deque

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    l = int(input_data[1])
    a = [int(x) for x in input_data[2:2+n]]
    
    pref = [0] * (n + 1)
    for i in range(n):
        pref[i + 1] = pref[i] + a[i]
        
    def cost(j, i):
        diff = (pref[i] - pref[j]) - l
        return diff * diff
        
    dp = [0] * (n + 1)
    
    def func(j, i):
        return dp[j] + cost(j, i)
        
    # deque stores elements (j, start_idx)
    # where j is the best transition for [start_idx, ...]
    dq = deque()
    dq.append((0, 1))
    
    for i in range(1, n + 1):
        # pop outdated intervals
        while len(dq) > 1 and dq[1][1] <= i:
            dq.popleft()
            
        best_j = dq[0][0]
        dp[i] = func(best_j, i)
        
        if i == n:
            break
            
        # binary search where i becomes better than dq[-1]
        while dq:
            last_j, start = dq[-1]
            if func(i, start) <= func(last_j, start):
                dq.pop()
            else:
                break
                
        if not dq:
            dq.append((i, i + 1))
        else:
            last_j, start = dq[-1]
            low = max(start, i + 1)
            high = n + 1
            idx = n + 1
            while low <= high:
                mid = (low + high) // 2
                if mid <= n and func(i, mid) <= func(last_j, mid):
                    idx = mid
                    high = mid - 1
                else:
                    low = mid + 1
            if idx <= n:
                dq.append((i, idx))
                
    print(dp[n])

if __name__ == '__main__':
    solve()
