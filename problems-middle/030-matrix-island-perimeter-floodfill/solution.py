import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    r, c = map(int, lines[0].split())
    grid = []
    for i in range(1, 1 + r):
        grid.append([int(x) for x in lines[i].split()])
        
    perimeter = 0
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    for i in range(r):
        for j in range(c):
            if grid[i][j] == 1:
                for k in range(4):
                    ni = i + dr[k]
                    nj = j + dc[k]
                    if ni < 0 or ni >= r or nj < 0 or nj >= c or grid[ni][nj] == 0:
                        perimeter += 1
                        
    print(perimeter)

if __name__ == "__main__":
    main()
