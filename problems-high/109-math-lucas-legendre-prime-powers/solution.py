import sys

def legendre(n, p):
    cnt = 0
    k = p
    while k <= n:
        cnt += n // k
        if k > n // p:
            break
        k *= p
    return cnt

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    t = int(input_data[0])
    idx = 1
    out = []
    for _ in range(t):
        n = int(input_data[idx])
        p = int(input_data[idx+1])
        idx += 2
        e1 = legendre(n, p)
        e2 = legendre(2 * n, p) - 2 * e1
        out.append(f"{e1} {e2}")
    print("\n".join(out))

if __name__ == '__main__':
    solve()
