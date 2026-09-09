import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    n, k = int(parts[0]), int(parts[1])
    
    coins = [int(lines[i].strip()) for i in range(1, 1 + n) if lines[i].strip()]
    
    ans = 0
    # 큰 동전부터 거꾸로 순회
    for c in reversed(coins):
        if k == 0:
            break
        if c <= k:
            ans += k // c
            k %= c
            
    print(ans)

if __name__ == "__main__":
    main()
