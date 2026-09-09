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
        
    visited = [[False] * c for _ in range(r)]
    dr = [0, 1, 0, -1]
    dc = [1, 0, -1, 0]
    
    cr, cc, d = 0, 0, 0
    res = []
    for _ in range(r * c):
        res.append(grid[cr][cc])
        visited[cr][cc] = True
        nr = cr + dr[d]
        nc = cc + dc[d]
        if nr < 0 or nr >= r or nc < 0 or nc >= c or visited[nr][nc]:
            d = (d + 1) % 4
            nr = cr + dr[d]
            nc = cc + dc[d]
        cr, cc = nr, nc
        
    print(" ".join(res))

if __name__ == "__main__":
    main()
