import sys

def to_base(n, b):
    digits = "0123456789ABCDEF"
    if n == 0:
        return "0"
    res = []
    while n > 0:
        res.append(digits[n % b])
        n //= b
    return "".join(reversed(res))

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    n, b = int(parts[0]), int(parts[1])
    print(to_base(n, b))

if __name__ == "__main__":
    main()
