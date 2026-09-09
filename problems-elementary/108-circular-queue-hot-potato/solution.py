import sys

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    n, m = int(parts[0]), int(parts[1])
    # 1번에서 시작하여 M번 이동
    ans = (m % n) + 1
    print(ans)

if __name__ == "__main__":
    main()
