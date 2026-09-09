import sys

MOD = 1000000007

def subset_convolution(n, a, b):
    size = 1 << n
    
    popcount = [0] * size
    for i in range(1, size):
        popcount[i] = popcount[i >> 1] + (i & 1)
        
    a_hat = [[0] * size for _ in range(n + 1)]
    b_hat = [[0] * size for _ in range(n + 1)]
    
    for i in range(size):
        c = popcount[i]
        a_hat[c][i] = a[i]
        b_hat[c][i] = b[i]
        
    for c in range(n + 1):
        for i in range(n):
            bit = 1 << i
            for mask in range(size):
                if mask & bit:
                    a_hat[c][mask] = (a_hat[c][mask] + a_hat[c][mask ^ bit]) % MOD
                    b_hat[c][mask] = (b_hat[c][mask] + b_hat[c][mask ^ bit]) % MOD
                    
    c_hat = [[0] * size for _ in range(n + 1)]
    for c in range(n + 1):
        for a_c in range(c + 1):
            b_c = c - a_c
            ac_arr = a_hat[a_c]
            bc_arr = b_hat[b_c]
            target = c_hat[c]
            for mask in range(size):
                target[mask] = (target[mask] + ac_arr[mask] * bc_arr[mask]) % MOD
                
    for c in range(n + 1):
        for i in range(n):
            bit = 1 << i
            for mask in range(size):
                if mask & bit:
                    c_hat[c][mask] = (c_hat[c][mask] - c_hat[c][mask ^ bit]) % MOD
                    if c_hat[c][mask] < 0:
                        c_hat[c][mask] += MOD
                        
    ans = [c_hat[popcount[i]][i] for i in range(size)]
    return ans

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    size = 1 << n
    a = [int(x) % MOD for x in input_data[1:1+size]]
    b = [int(x) % MOD for x in input_data[1+size:1+2*size]]
    
    c = subset_convolution(n, a, b)
    print(' '.join(map(str, c)))

if __name__ == '__main__':
    main()
