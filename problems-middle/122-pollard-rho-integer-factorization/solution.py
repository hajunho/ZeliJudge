import sys
import math

def gcd(a, b):
    while b:
        a, b = b, a % b
    return a

def power(base, exp, mod):
    res = 1
    base %= mod
    while exp > 0:
        if exp % 2 == 1:
            res = (res * base) % mod
        base = (base * base) % mod
        exp //= 2
    return res

def miller_rabin(n, a):
    if n % a == 0:
        return False
    d = n - 1
    while d % 2 == 0:
        d //= 2
    x = power(a, d, n)
    if x == 1 or x == n - 1:
        return True
    while d != n - 1:
        x = (x * x) % n
        d *= 2
        if x == n - 1:
            return True
        if x == 1:
            return False
    return False

def is_prime(n):
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    for a in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]:
        if n == a:
            return True
        if not miller_rabin(n, a):
            return False
    return True

def pollard_rho(n):
    if n % 2 == 0:
        return 2
    if is_prime(n):
        return n
    x = 2
    y = 2
    c = 1
    d = 1
    f = lambda v: (v * v + c) % n
    while d == 1:
        x = f(x)
        y = f(f(y))
        d = gcd(abs(x - y), n)
        if d == n:
            # retry with different c
            x = 2
            y = 2
            c += 1
            d = 1
    return d

def factorize(n):
    factors = []
    stack = [n]
    while stack:
        curr = stack.pop()
        if curr == 1:
            continue
        if is_prime(curr):
            factors.append(curr)
            continue
        d = pollard_rho(curr)
        stack.append(d)
        stack.append(curr // d)
    factors.sort()
    return factors

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    factors = factorize(N)
    print(' '.join(map(str, factors)))

if __name__ == "__main__":
    solve()
