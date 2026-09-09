import sys

def ext_gcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x1, y1 = ext_gcd(b, a % b)
    x = y1
    y = x1 - (a // b) * y1
    return g, x, y

def general_crt(congs):
    r1, m1 = congs[0]
    r1 %= m1
    
    for r2, m2 in congs[1:]:
        r2 %= m2
        # m1 * p + m2 * q = r2 - r1
        g, p, q = ext_gcd(m1, m2)
        diff = r2 - r1
        if diff % g != 0:
            return -1
            
        step = m2 // g
        p = (p * (diff // g)) % step
        if p < 0:
            p += step
            
        new_r = r1 + m1 * p
        new_m = m1 * step
        r1 = new_r % new_m
        m1 = new_m
        
    return r1

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    congs = []
    idx = 1
    for _ in range(n):
        r = int(input_data[idx])
        m = int(input_data[idx + 1])
        congs.append((r, m))
        idx += 2
        
    ans = general_crt(congs)
    print(ans)

if __name__ == '__main__':
    main()
