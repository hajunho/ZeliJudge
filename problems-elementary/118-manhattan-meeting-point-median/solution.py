import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    xs = []
    ys = []
    for i in range(1, 1 + n):
        parts = lines[i].split()
        xs.append(int(parts[0]))
        ys.append(int(parts[1]))
        
    xs.sort()
    ys.sort()
    mid = n // 2
    print(f"{xs[mid]} {ys[mid]}")

if __name__ == "__main__":
    main()
