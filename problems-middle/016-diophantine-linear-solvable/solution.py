import sys
import math

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    a, b, c = map(int, line.split())
    
    g = math.gcd(a, b)
    if c % g == 0:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
