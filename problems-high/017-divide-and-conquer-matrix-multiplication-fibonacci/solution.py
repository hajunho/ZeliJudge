import sys

MOD = 1000000007

def mat_mul(a, b):
    return [
        [(a[0][0]*b[0][0] + a[0][1]*b[1][0]) % MOD, (a[0][0]*b[0][1] + a[0][1]*b[1][1]) % MOD],
        [(a[1][0]*b[0][0] + a[1][1]*b[1][0]) % MOD, (a[1][0]*b[0][1] + a[1][1]*b[1][1]) % MOD]
    ]

def mat_pow(mat, p):
    res = [[1, 0], [0, 1]]
    base = mat
    while p > 0:
        if p % 2 == 1:
            res = mat_mul(res, base)
        base = mat_mul(base, base)
        p //= 2
    return res

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    if n == 0:
        print(0)
        return
        
    t = [[1, 1], [1, 0]]
    res = mat_pow(t, n)
    # res[0][1] = F_n
    print(res[0][1])

if __name__ == "__main__":
    solve()
