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
        
    dist = [[-1] * c for _ in range(r)]
    q = deque([(0, 0)])
    dist[0][0] = 1
    
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    while q:
        cr, cc = q.popleft()
        if cr == r - 1 and cc == c - 1:
            print(dist[cr][cc])
            return
            
        for d in range(4):
            nr = cr + dr[d]
            nc = cc + dc[d]
            if 0 <= nr < r and 0 <= nc < c and grid[nr][nc] == 0 and dist[nr][nc] == -1:
                dist[nr][nc] = dist[cr][cc] + 1
                q.append((nr, nc))
                
    print(-1)

if __name__ == "__main__":
    main()
