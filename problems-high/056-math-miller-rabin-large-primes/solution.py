import sys

def power_mod(base, exp, mod):
    res = 1
    base %= mod
    while exp > 0:
        if exp % 2 == 1:
            res = (res * base) % mod
        base = (base * base) % mod
        exp //= 2
    return res

def is_prime(n):
    if n <= 1:
        return False
    if n in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        return True
    if n % 2 == 0:
        return False
        
    d = n - 1
    s = 0
    while d % 2 == 0:
        d //= 2
        s += 1
        
    bases = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
    for a in bases:
        if a >= n:
            continue
        x = power_mod(a, d, n)
        if x == 1 or x == n - 1:
            continue
        composite = True
        for _ in range(s - 1):
            x = power_mod(x, 2, n)
            if x == n - 1:
                composite = False
                break
        if composite:
            return False
    return True

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    n = int(lines[0])
    print("PRIME" if is_prime(n) else "COMPOSITE")

if __name__ == "__main__":
    solve()
