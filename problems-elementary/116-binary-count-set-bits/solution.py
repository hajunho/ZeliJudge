import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    print(bin(n).count('1'))

if __name__ == "__main__":
    main()
