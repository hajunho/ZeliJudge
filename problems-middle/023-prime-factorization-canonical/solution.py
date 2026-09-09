import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    
    factors = []
    
    # 2로 나누기
    if n % 2 == 0:
        exp = 0
        while n % 2 == 0:
            exp += 1
            n //= 2
        factors.append((2, exp))
        
    # 3부터 홀수로 나누기
    d = 3
    while d * d <= n:
        if n % d == 0:
            exp = 0
            while n % d == 0:
                exp += 1
                n //= d
            factors.append((d, exp))
        d += 2
        
    if n > 1:
        factors.append((n, 1))
        
    formatted = [f"{p}^{e}" if e > 1 else str(p) for p, e in factors]
    print(" * ".join(formatted))

if __name__ == "__main__":
    main()
