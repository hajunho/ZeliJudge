import sys

MOD = 998244353

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    a = [int(x) for x in input_data[1:2+n]]
    
    # Derivative P'(x): deg n-1
    deriv = [(i * a[i]) % MOD for i in range(1, n + 1)]
    
    # Precompute inverses up to n + 1 in O(N)
    inv = [0] * (n + 2)
    inv[1] = 1
    for i in range(2, n + 2):
        inv[i] = (MOD - MOD // i) * inv[MOD % i] % MOD
        
    # Integral \int P(x) dx: deg n+1
    integral = [0] * (n + 2)
    for i in range(n + 1):
        integral[i + 1] = (a[i] * inv[i + 1]) % MOD
        
    print(" ".join(map(str, deriv)))
    print(" ".join(map(str, integral)))

if __name__ == '__main__':
    solve()
