import sys
import math
import random

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
        
    for a in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]:
        if a >= n:
            continue
        x = power_mod(a, d, n)
        if x == 1 or x == n - 1:
            continue
        comp = True
        for _ in range(s - 1):
            x = power_mod(x, 2, n)
            if x == n - 1:
                comp = False
                break
        if comp:
            return False
    return True

def pollard_rho(n):
    if is_prime(n):
        return n
    if n % 2 == 0:
        return 2
    x = random.randint(2, n - 1)
    y = x
    c = random.randint(1, n - 1)
    g = 1
    while g == 1:
        x = ((x * x) % n + c) % n
        y = ((y * y) % n + c) % n
        y = ((y * y) % n + c) % n
        g = math.gcd(abs(x - y), n)
        if g == n:
            return pollard_rho(n)
    if is_prime(g):
        return g
    return pollard_rho(g)

def factorize(n, factors):
    while n > 1:
        f = pollard_rho(n)
        while n % f == 0:
            factors.append(f)
            n //= f

def solve():
    random.seed(42)
    lines = sys.stdin.read().split()
    if not lines:
        return
    n = int(lines[0])
    factors = []
    factorize(n, factors)
    factors.sort()
    for f in factors:
        print(f)

if __name__ == "__main__":
    solve()
