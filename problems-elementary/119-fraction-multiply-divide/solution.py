import sys

def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    op = parts[0]
    a, b, c, d = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
    
    if op == '*':
        numer = a * c
        denom = b * d
    elif op == '/':
        numer = a * d
        denom = b * c
        
    g = gcd(numer, denom)
    print(f"{numer // g} {denom // g}")

if __name__ == "__main__":
    main()
