import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c = int(parts[0]), int(parts[1])
    
    grid = []
    for i in range(1, 1 + r):
        grid.append(lines[i].split())
        
    # 시계방향 90도 회전: zip(*grid[::-1])
    rotated = list(zip(*grid[::-1]))
    for row in rotated:
        print(" ".join(row))

if __name__ == "__main__":
    main()
