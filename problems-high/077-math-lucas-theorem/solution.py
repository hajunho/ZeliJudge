import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k = int(input_data[1])
    p = int(input_data[2])
    
    if k > n:
        print(0)
        return
    if k == 0 or k == n:
        print(1)
        return
        
    fact = [1] * p
    inv_fact = [1] * p
    for i in range(1, p):
        fact[i] = (fact[i - 1] * i) % p
        
    inv_fact[p - 1] = pow(fact[p - 1], p - 2, p)
    for i in range(p - 2, -1, -1):
        inv_fact[i] = (inv_fact[i + 1] * (i + 1)) % p
        
    def small_comb(n_sub, k_sub):
        if k_sub < 0 or k_sub > n_sub:
            return 0
        return (fact[n_sub] * inv_fact[k_sub] % p) * inv_fact[n_sub - k_sub] % p

    ans = 1
    while n > 0 or k > 0:
        ni = n % p
        ki = k % p
        if ki > ni:
            ans = 0
            break
        ans = (ans * small_comb(ni, ki)) % p
        n //= p
        k //= p
        
    print(ans)

if __name__ == '__main__':
    main()
