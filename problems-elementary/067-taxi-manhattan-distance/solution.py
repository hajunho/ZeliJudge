import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    total_dist = 0
    for i in range(1, n + 1):
        parts = lines[i].split()
        x1, y1, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        dist = abs(x1 - x2) + abs(y1 - y2)
        total_dist += dist
        
    print(total_dist)

if __name__ == "__main__":
    main()
