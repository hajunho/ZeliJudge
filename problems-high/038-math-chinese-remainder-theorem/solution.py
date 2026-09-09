import sys

def ext_gcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x1, y1 = ext_gcd(b, a % b)
    return g, y1, x1 - (a // b) * y1

def mod_inv(a, m):
    g, x, _ = ext_gcd(a, m)
    return (x % m + m) % m

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    k = int(input_data[0])
    
    a_list = []
    m_list = []
    idx = 1
    M = 1
    for _ in range(k):
        a = int(input_data[idx])
        m = int(input_data[idx+1])
        idx += 2
        a_list.append(a)
        m_list.append(m)
        M *= m
        
    x = 0
    for i in range(k):
        Mi = M // m_list[i]
        ti = mod_inv(Mi, m_list[i])
        x = (x + a_list[i] * Mi * ti) % M
        
    if x == 0:
        x = M
    print(x)

if __name__ == "__main__":
    solve()
