import sys
import math

MOD = 1000000007

def power(base, exp):
    res = 1
    base %= MOD
    while exp > 0:
        if exp % 2 == 1:
            res = (res * base) % MOD
        base = (base * base) % MOD
        exp //= 2
    return res

def mod_inv(n):
    return power(n, MOD - 2)

def solve(n, c):
    if n == 1:
        return c % MOD
    
    total = 0
    # 1. Rotations
    for k in range(n):
        g = math.gcd(k, n)
        total = (total + power(c, g)) % MOD
        
    # 2. Reflections
    if n % 2 == 1:
        # N reflections with (n + 1) // 2 cycles
        cycles = (n + 1) // 2
        refl = (n * power(c, cycles)) % MOD
        total = (total + refl) % MOD
    else:
        # n/2 reflections through vertices: n/2 + 1 cycles
        # n/2 reflections through edges: n/2 cycles
        refl1 = ((n // 2) * power(c, n // 2 + 1)) % MOD
        refl2 = ((n // 2) * power(c, n // 2)) % MOD
        total = (total + refl1 + refl2) % MOD
        
    ans = (total * mod_inv(2 * n)) % MOD
    return ans

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    t = int(input_data[0])
    idx = 1
    out = []
    for _ in range(t):
        n = int(input_data[idx])
        c = int(input_data[idx + 1])
        idx += 2
        out.append(str(solve(n, c)))
    print('\n'.join(out))

if __name__ == '__main__':
    main()
