import sys

def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    a, b = int(parts[0]), int(parts[1])
    g = gcd(a, b)
    l = (a * b) // g
    print(f"{g} {l}")

if __name__ == "__main__":
    main()
