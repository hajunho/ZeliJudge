import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    K = int(lines[1])
    primes = [int(x) for x in lines[2:2+K]]
    
    total = 0
    # Iterate over all non-empty subsets using bitmask
    for mask in range(1, 1 << K):
        prod = 1
        bits = 0
        overflow = False
        for i in range(K):
            if (mask >> i) & 1:
                prod *= primes[i]
                bits += 1
                if prod > N:
                    overflow = True
                    break
        if overflow:
            continue
            
        count = N // prod
        if bits % 2 == 1:
            total += count
        else:
            total -= count
            
    print(total)

if __name__ == "__main__":
    solve()
