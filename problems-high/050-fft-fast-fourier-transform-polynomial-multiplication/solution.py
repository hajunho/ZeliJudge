import sys
import cmath

def fft(a, invert=False):
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
            
    length = 2
    while length <= n:
        angle = 2 * cmath.pi / length * (-1 if invert else 1)
        wlen = cmath.rect(1.0, angle)
        for i in range(0, n, length):
            w = 1.0 + 0.0j
            for k in range(length // 2):
                u = a[i + k]
                v = a[i + k + length // 2] * w
                a[i + k] = u + v
                a[i + k + length // 2] = u - v
                w *= wlen
        length <<= 1
        
    if invert:
        for i in range(n):
            a[i] /= n

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    a_coeffs = [int(x) for x in input_data[2:2+n+1]]
    b_coeffs = [int(x) for x in input_data[2+n+1:2+n+1+m+1]]
    
    deg = n + m
    size = 1
    while size <= deg:
        size <<= 1
        
    fa = [complex(x, 0) for x in a_coeffs] + [0j] * (size - len(a_coeffs))
    fb = [complex(x, 0) for x in b_coeffs] + [0j] * (size - len(b_coeffs))
    
    fft(fa, False)
    fft(fb, False)
    
    for i in range(size):
        fa[i] *= fb[i]
        
    fft(fa, True)
    
    res = [round(fa[i].real) for i in range(deg + 1)]
    print(*(res))

if __name__ == "__main__":
    solve()
