import sys

MOD = 1000000007

def mat_mul(A, B):
    C = [[0, 0], [0, 0]]
    for i in range(2):
        for j in range(2):
            s = 0
            for k in range(2):
                s = (s + A[i][k] * B[k][j]) % MOD
            C[i][j] = s
    return C

def mat_pow(A, p):
    res = [[1, 0], [0, 1]]
    base = A
    while p > 0:
        if p & 1:
            res = mat_mul(res, base)
        base = mat_mul(base, base)
        p >>= 1
    return res

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    
    if N == 0:
        print(0)
        return
    if N == 1:
        print(1)
        return
        
    # [ [1, 1], [1, 0] ] ^ (N - 1)
    T = [[1, 1], [1, 0]]
    TN = mat_pow(T, N - 1)
    # F(N) = TN[0][0] * F(1) + TN[0][1] * F(0) = TN[0][0] * 1 + 0 = TN[0][0]
    ans = TN[0][0] % MOD
    print(ans)

if __name__ == "__main__":
    solve()
