import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    a = lines[0].strip()
    b = lines[1].strip()
    
    diff = sum(1 for c1, c2 in zip(a, b) if c1 != c2)
    if diff == 1:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
