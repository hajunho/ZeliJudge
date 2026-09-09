import sys

MAX_V = 1000000

def sieve_mobius(limit=MAX_V):
    mu = [0] * (limit + 1)
    primes = []
    is_prime = [True] * (limit + 1)
    mu[1] = 1
    
    for i in range(2, limit + 1):
        if is_prime[i]:
            primes.append(i)
            mu[i] = -1
        for p in primes:
            if i * p > limit:
                break
            is_prime[i * p] = False
            if i % p == 0:
                mu[i * p] = 0
                break
            else:
                mu[i * p] = -mu[i]
                
    pref_mu = [0] * (limit + 1)
    for i in range(1, limit + 1):
        pref_mu[i] = pref_mu[i - 1] + mu[i]
        
    return pref_mu

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    t = int(input_data[0])
    
    pref_mu = sieve_mobius(MAX_V)
    
    idx = 1
    out = []
    for _ in range(t):
        n = int(input_data[idx])
        m = int(input_data[idx + 1])
        idx += 2
        
        limit = min(n, m)
        ans = 0
        l = 1
        while l <= limit:
            r = min(n // (n // l), m // (m // l))
            ans += (pref_mu[r] - pref_mu[l - 1]) * (n // l) * (m // l)
            l = r + 1
            
        out.append(str(ans))
        
    print('\n'.join(out))

if __name__ == '__main__':
    solve()
