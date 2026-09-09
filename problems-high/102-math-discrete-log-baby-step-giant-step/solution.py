import sys
import math

def bsgs(a, b, p):
    a %= p
    b %= p
    if b == 1:
        return 0
    if a == 0:
        return 0 if b == 0 else -1
        
    m = int(math.isqrt(p)) + 1
    
    # Baby steps: val = (b * a^j) % p
    table = {}
    cur = b
    for j in range(m):
        table[cur] = j
        cur = (cur * a) % p
        
    # Giant steps: cur = (a^m)^i % p
    am = pow(a, m, p)
    cur = 1
    for i in range(1, m + 1):
        cur = (cur * am) % p
        if cur in table:
            ans = i * m - table[cur]
            return ans
            
    return -1

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    t = int(input_data[0])
    idx = 1
    out = []
    for _ in range(t):
        a = int(input_data[idx])
        b = int(input_data[idx+1])
        p = int(input_data[idx+2])
        idx += 3
        out.append(str(bsgs(a, b, p)))
    print("\n".join(out))

if __name__ == '__main__':
    solve()
