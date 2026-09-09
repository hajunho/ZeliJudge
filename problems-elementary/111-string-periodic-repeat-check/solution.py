import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
    n = len(s)
    
    for k in range(1, n // 2 + 1):
        if n % k == 0:
            unit = s[:k]
            if unit * (n // k) == s:
                print("YES")
                return
                
    print("NO")

if __name__ == "__main__":
    main()
