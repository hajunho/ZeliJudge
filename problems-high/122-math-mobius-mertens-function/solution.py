import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    # Precompute up to K = max(1000, int(n**(2/3)))
    K = min(n, max(5000000, int(n**(2/3))))
    mu = [0] * (K + 1)
    primes = []
    is_prime = [True] * (K + 1)
    is_prime[0] = is_prime[1] = False
    mu[1] = 1
    
    for i in range(2, K + 1):
        if is_prime[i]:
            primes.append(i)
            mu[i] = -1
        for p in primes:
            if i * p > K:
                break
            is_prime[i * p] = False
            if i % p == 0:
                mu[i * p] = 0
                break
            else:
                mu[i * p] = -mu[i]
                
    pref_mu = [0] * (K + 1)
    for i in range(1, K + 1):
        pref_mu[i] = pref_mu[i - 1] + mu[i]
        
    memo = {}
    
    def get_mertens(val):
        if val <= K:
            return pref_mu[val]
        if val in memo:
            return memo[val]
            
        res = 1
        l = 2
        while l <= val:
            q = val // l
            r = val // q
            res -= (r - l + 1) * get_mertens(q)
            l = r + 1
            
        memo[val] = res
        return res

    print(get_mertens(n))

if __name__ == '__main__':
    solve()
