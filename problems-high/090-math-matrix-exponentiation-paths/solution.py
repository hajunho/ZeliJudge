import sys

MOD = 1000000007

def mat_mul(a, b, v):
    c = [[0] * v for _ in range(v)]
    for i in range(v):
        for k in range(v):
            if not a[i][k]:
                continue
            for j in range(v):
                c[i][j] = (c[i][j] + a[i][k] * b[k][j]) % MOD
    return c

def mat_pow(mat, exp, v):
    res = [[1 if i == j else 0 for j in range(v)] for i in range(v)]
    base = mat
    while exp > 0:
        if exp % 2 == 1:
            res = mat_mul(res, base, v)
        if exp > 1:
            base = mat_mul(base, base, v)
        exp //= 2
    return res

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    m = int(input_data[1])
    k = int(input_data[2])
    s = int(input_data[3]) - 1
    e = int(input_data[4]) - 1
    
    adj = [[0] * v for _ in range(v)]
    idx = 5
    for _ in range(m):
        u = int(input_data[idx]) - 1
        to = int(input_data[idx + 1]) - 1
        adj[u][to] = (adj[u][to] + 1) % MOD
        idx += 2
        
    res_mat = mat_pow(adj, k, v)
    print(res_mat[s][e])

if __name__ == '__main__':
    main()
