import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c = int(parts[0]), int(parts[1])
    
    grid = []
    for i in range(1, 1 + r):
        grid.append([int(x) for x in lines[i].split()])
        
    col_sums = []
    for j in range(c):
        s = sum(grid[i][j] for i in range(r))
        col_sums.append(s)
        
    print(" ".join(map(str, col_sums)))

if __name__ == "__main__":
    main()
