import sys

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
    # Deterministic bases for 64-bit integers
    bases = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
    for a in bases:
        if n == a:
            return True
        if not miller_rabin(n, a):
            return False
    return True

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    T = int(lines[0])
    out = []
    for i in range(1, 1 + T):
        n = int(lines[i])
        if is_prime(n):
            out.append("YES")
        else:
            out.append("NO")
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
