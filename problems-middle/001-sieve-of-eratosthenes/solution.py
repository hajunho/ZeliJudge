import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    
    is_prime = [True] * (n + 1)
    is_prime[0] = is_prime[1] = False
    
    p = 2
    while p * p <= n:
        if is_prime[p]:
            for multiple in range(p * p, n + 1, p):
                is_prime[multiple] = False
        p += 1
        
    primes = [str(i) for i in range(2, n + 1) if is_prime[i]]
    print(" ".join(primes))

if __name__ == "__main__":
    main()
