import sys

MOD = 1000000007

def power(base, exp):
    res = 1
    base %= MOD
    while exp > 0:
        if exp % 2 == 1:
            res = (res * base) % MOD
        base = (base * base) % MOD
        exp //= 2
    return res

def mod_inv(n):
    return power(n, MOD - 2)

def precompute_bernoulli(max_k):
    # Precompute B_0 to B_{max_k} with B_1 = +1/2
    B = [0] * (max_k + 1)
    B[0] = 1
    
    # Precompute factorials and inverses for combinations
    fact = [1] * (max_k + 3)
    inv_fact = [1] * (max_k + 3)
    for i in range(1, max_k + 3):
        fact[i] = (fact[i - 1] * i) % MOD
    inv_fact[max_k + 2] = mod_inv(fact[max_k + 2])
    for i in range(max_k + 1, -1, -1):
        inv_fact[i] = (inv_fact[i + 1] * (i + 1)) % MOD
        
    def nCr(n, r):
        if r < 0 or r > n:
            return 0
        return (fact[n] * inv_fact[r] % MOD) * inv_fact[n - r] % MOD

    for m in range(1, max_k + 1):
        s = 0
        for j in range(m):
            s = (s + nCr(m + 1, j) * B[j]) % MOD
        B[m] = (-s * mod_inv(m + 1)) % MOD
        B[m] = (B[m] + MOD) % MOD
        
    # Faulhaber formula for sum_{i=1}^N uses B_1 = +1/2
    if max_k >= 1:
        B[1] = mod_inv(2)
        
    return B, fact, inv_fact, nCr

def faulhaber(n, k):
    B, fact, inv_fact, nCr = precompute_bernoulli(k)
    
    # S_k(N) = 1/(k+1) * sum_{j=0}^k nCr(k+1, j) * B_j * N^{k+1-j}
    ans = 0
    cur_n_pow = power(n, 1) # will maintain N^{k+1-j}
    # precompute powers of N from 1 to k+1
    n_mod = n % MOD
    n_pows = [1] * (k + 2)
    for i in range(1, k + 2):
        n_pows[i] = (n_pows[i - 1] * n_mod) % MOD
        
    for j in range(k + 1):
        term = nCr(k + 1, j)
        term = (term * B[j]) % MOD
        term = (term * n_pows[k + 1 - j]) % MOD
        ans = (ans + term) % MOD
        
    ans = (ans * mod_inv(k + 1)) % MOD
    return ans

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k = int(input_data[1])
    ans = faulhaber(n, k)
    print(ans)

if __name__ == '__main__':
    main()
