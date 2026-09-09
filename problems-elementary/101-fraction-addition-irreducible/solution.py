import sys

def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    a, b, c, d = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    
    numer = a * d + b * c
    denom = b * d
    g = gcd(numer, denom)
    
    print(f"{numer // g} {denom // g}")

if __name__ == "__main__":
    main()
