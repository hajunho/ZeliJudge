import sys

def ext_gcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x1, y1 = ext_gcd(b, a % b)
    x = y1
    y = x1 - (a // b) * y1
    return g, x, y

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    r1 = int(lines[0])
    m1 = int(lines[1])
    r2 = int(lines[2])
    m2 = int(lines[3])
    
    # x = r1 mod m1, x = r2 mod m2
    # m1 * p + m2 * q = 1
    g, p, q = ext_gcd(m1, m2)
    
    M = m1 * m2
    # x = r1 * m2 * q + r2 * m1 * p
    ans = (r1 * m2 * q + r2 * m1 * p) % M
    ans = (ans + M) % M
    
    if ans == 0:
        ans = M
        
    print(ans)

if __name__ == "__main__":
    solve()
