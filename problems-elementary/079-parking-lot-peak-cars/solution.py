import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    timeline = [0] * 101
    for i in range(1, n + 1):
        parts = lines[i].split()
        s, e = int(parts[0]), int(parts[1])
        for t in range(s, e):
            timeline[t] += 1
            
    print(max(timeline))

if __name__ == "__main__":
    main()
