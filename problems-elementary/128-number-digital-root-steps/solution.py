import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    
    steps = 0
    while n >= 10:
        n = sum(int(ch) for ch in str(n))
        steps += 1
        
    print(steps)

if __name__ == "__main__":
    main()
