import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    t = lines[0].strip()
    p = lines[1].strip()
    
    idx = t.find(p)
    if idx == -1:
        print(-1)
    else:
        print(idx + 1)

if __name__ == "__main__":
    main()
