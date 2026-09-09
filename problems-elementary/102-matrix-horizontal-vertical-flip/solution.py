import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c, cmd = int(parts[0]), int(parts[1]), parts[2]
    
    grid = []
    for i in range(1, 1 + r):
        grid.append(lines[i].split())
        
    if cmd == 'H':
        for row in grid:
            print(" ".join(row[::-1]))
    elif cmd == 'V':
        for row in grid[::-1]:
            print(" ".join(row))

if __name__ == "__main__":
    main()
