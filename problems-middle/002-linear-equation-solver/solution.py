import sys
import math

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    a, b, c = map(int, line.split())
    
    num = c - b
    den = a
    
    if num % den == 0:
        print(num // den)
    else:
        if den < 0:
            num = -num
            den = -den
        g = math.gcd(abs(num), abs(den))
        num //= g
        den //= g
        print(f"{num}/{den}")

if __name__ == "__main__":
    main()
