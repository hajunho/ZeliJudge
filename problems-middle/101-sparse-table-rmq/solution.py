import sys
import math

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    Q = int(lines[1])
    idx = 2
    arr = [int(x) for x in lines[idx:idx+N]]
    idx += N
    
    # Precompute Sparse Table
    # ST[k][i]: min in range [i, i + 2^k - 1]
    K = math.floor(math.log2(N)) + 1 if N > 0 else 1
    ST = [[0] * N for _ in range(K)]
    for i in range(N):
        ST[0][i] = arr[i]
        
    for k in range(1, K):
        step = 1 << (k - 1)
        for i in range(N):
            if i + step < N:
                ST[k][i] = min(ST[k-1][i], ST[k-1][i + step])
            else:
                ST[k][i] = ST[k-1][i]
                
    out = []
    for _ in range(Q):
        L = int(lines[idx]) - 1
        R = int(lines[idx+1]) - 1
        idx += 2
        length = R - L + 1
        k = math.floor(math.log2(length))
        ans = min(ST[k][L], ST[k][R - (1 << k) + 1])
        out.append(str(ans))
        
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
