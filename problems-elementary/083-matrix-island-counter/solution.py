import sys
from collections import deque

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c = int(parts[0]), int(parts[1])
    
    grid = []
    for i in range(1, 1 + r):
        grid.append([int(x) for x in lines[i].split()])
        
    visited = [[False] * c for _ in range(r)]
    island_count = 0
    
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    for i in range(r):
        for j in range(c):
            if grid[i][j] == 1 and not visited[i][j]:
                island_count += 1
                q = deque([(i, j)])
                visited[i][j] = True
                while q:
                    cr, cc = q.popleft()
                    for d in range(4):
                        nr = cr + dr[d]
                        nc = cc + dc[d]
                        if 0 <= nr < r and 0 <= nc < c:
                            if grid[nr][nc] == 1 and not visited[nr][nc]:
                                visited[nr][nc] = True
                                q.append((nr, nc))
                                
    print(island_count)

if __name__ == "__main__":
    main()
