import sys
from collections import deque

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k = int(input_data[1])
    a = [int(x) for x in input_data[2:2+n]]
    
    dq = deque([(0, 0)]) # (index, dp_value)
    
    dp = 0
    for i in range(1, n + 1):
        while dq and dq[0][0] < i - k:
            dq.popleft()
            
        dp = dq[0][1] + a[i - 1]
        
        while dq and dq[-1][1] <= dp:
            dq.pop()
        dq.append((i, dp))
        
    print(dp)

if __name__ == '__main__':
    solve()
