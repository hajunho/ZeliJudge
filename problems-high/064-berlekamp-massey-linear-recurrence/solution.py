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

def berlekamp_massey(s):
    # s is a list of elements mod MOD
    # returns recurrence c: s_i = sum_{j=1}^L c[j-1] * s_{i-j}
    c = []
    b = []
    last_m = -1
    last_d = 0
    
    for i in range(len(s)):
        # calculate discrepancy
        d = s[i]
        for j in range(len(c)):
            d = (d - c[j] * s[i - 1 - j]) % MOD
        d = (d + MOD) % MOD
        if d == 0:
            continue
        
        if not c:
            c = [0] * (i + 1)
            b = []
            last_m = i
            last_d = d
        else:
            scale = (d * mod_inv(last_d)) % MOD
            # temp = c - scale * x^(i - last_m) * (1 - B(x))
            k = i - last_m
            new_c = list(c)
            # length might need extension
            needed_len = max(len(c), k + len(b))
            while len(new_c) < needed_len:
                new_c.append(0)
            
            # add scale to pos k-1
            new_c[k - 1] = (new_c[k - 1] + scale) % MOD
            for j in range(len(b)):
                new_c[k + j] = (new_c[k + j] - scale * b[j]) % MOD
                new_c[k + j] = (new_c[k + j] + MOD) % MOD
            
            if len(c) < k + len(b):
                b = list(c)
                c = new_c
                last_m = i
                last_d = d
            else:
                c = new_c
                
    # remove trailing zeros if any
    while c and c[-1] == 0:
        c.pop()
    return c

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    s = [int(x) % MOD for x in input_data[1:1+n]]
    
    c = berlekamp_massey(s)
    l = len(c)
    print(l)
    if l > 0:
        print(' '.join(map(str, c)))

if __name__ == '__main__':
    main()
