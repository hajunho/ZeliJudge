import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    phi = [0] * (n + 1)
    phi[1] = 1
    primes = []
    is_prime = [True] * (n + 1)
    
    for i in range(2, n + 1):
        if is_prime[i]:
            primes.append(i)
            phi[i] = i - 1
        for p in primes:
            if i * p > n:
                break
            is_prime[i * p] = False
            if i % p == 0:
                phi[i * p] = phi[i] * p
                break
            else:
                phi[i * p] = phi[i] * (p - 1)
                
    ans = sum(phi)
    print(ans)

if __name__ == '__main__':
    solve()
