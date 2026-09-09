import sys

MOD = 1000000007

def poly_mult_mod(p1, p2, c, k):
    # p1, p2 are of degree < k
    # P(x) = x^k - sum_{i=1}^k c_i x^{k-i}
    # x^k = sum_{i=1}^k c_i x^{k-i}
    prod = [0] * (2 * k)
    for i in range(len(p1)):
        if not p1[i]:
            continue
        for j in range(len(p2)):
            prod[i + j] = (prod[i + j] + p1[i] * p2[j]) % MOD
            
    for deg in range(2 * k - 2, k - 1, -1):
        if prod[deg] == 0:
            continue
        coeff = prod[deg]
        prod[deg] = 0
        for i in range(1, k + 1):
            prod[deg - i] = (prod[deg - i] + coeff * c[i - 1]) % MOD
            
    return prod[:k]

def kitamasa(k, n, c, a):
    if n < k:
        return a[n] % MOD
    
    # Compute x^N mod P(x)
    res = [0] * k
    res[0] = 1 # poly 1
    base = [0] * k
    if k > 1:
        base[1] = 1 # poly x
    else:
        base[0] = c[0]
        
    exp = n
    while exp > 0:
        if exp % 2 == 1:
            res = poly_mult_mod(res, base, c, k)
        if exp > 1:
            base = poly_mult_mod(base, base, c, k)
        exp //= 2
        
    ans = 0
    for i in range(k):
        ans = (ans + res[i] * a[i]) % MOD
    return ans

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    k = int(input_data[0])
    n = int(input_data[1])
    c = [int(x) % MOD for x in input_data[2:2+k]]
    a = [int(x) % MOD for x in input_data[2+k:2+2*k]]
    
    ans = kitamasa(k, n, c, a)
    print(ans)

if __name__ == '__main__':
    main()
