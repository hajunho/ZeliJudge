import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    b = bin(n)[2:]
    if b == b[::-1]:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
