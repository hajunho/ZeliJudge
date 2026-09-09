import sys
from collections import deque

# Line: y = m * x + c
# We want min(m * x + c)
# m is strictly decreasing: m1 > m2 > ...
# x is non-decreasing: x1 <= x2 <= ...

def intersect_x(l1, l2):
    # m1 * x + c1 = m2 * x + c2 => x = (c2 - c1) / (m1 - m2)
    # Since m1 > m2, denominator > 0
    return (l2[1] - l1[1]) / (l1[0] - l2[0])

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    dq = deque()
    idx = 1
    out = []
    
    for _ in range(n):
        m = int(input_data[idx])
        c = int(input_data[idx+1])
        x = int(input_data[idx+2])
        idx += 3
        
        new_line = (m, c)
        
        # Add new line to deque: pop while intersect_x(dq[-2], dq[-1]) >= intersect_x(dq[-1], new_line)
        while len(dq) >= 2 and intersect_x(dq[-2], dq[-1]) >= intersect_x(dq[-1], new_line):
            dq.pop()
        dq.append(new_line)
        
        # Query x: pop front while intersect_x(dq[0], dq[1]) <= x
        while len(dq) >= 2 and intersect_x(dq[0], dq[1]) <= x:
            dq.popleft()
            
        best = dq[0][0] * x + dq[0][1]
        out.append(str(best))
        
    print("\n".join(out))

if __name__ == '__main__':
    solve()
