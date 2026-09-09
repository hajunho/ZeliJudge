import sys

def ext_gcd(a, b):
    if b == 0:
        return 1, 0, a
    x1, y1, g = ext_gcd(b, a % b)
    x = y1
    y = x1 - (a // b) * y1
    return x, y, g

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    a = int(lines[0])
    b = int(lines[1])
    x, y, g = ext_gcd(a, b)
    print(f"{x} {y} {g}")

if __name__ == "__main__":
    solve()
