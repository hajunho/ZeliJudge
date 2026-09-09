import sys

def power_mod(a, b, c):
    res = 1
    a %= c
    while b > 0:
        if b % 2 == 1:
            res = (res * a) % c
        a = (a * a) % c
        b //= 2
    return res

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    a, b, c = map(int, line.split())
    print(power_mod(a, b, c))

if __name__ == "__main__":
    main()
