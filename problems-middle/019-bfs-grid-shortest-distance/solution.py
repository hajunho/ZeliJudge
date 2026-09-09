import sys
from collections import deque

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c = int(parts[0]), int(parts[1])
    grid = [lines[i].strip() for i in range(1, 1 + r)]
    
    dist = [[-1] * c for _ in range(r)]
    dist[0][0] = 1
    
    q = deque([(0, 0)])
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    while q:
        cr, cc = q.popleft()
        if cr == r - 1 and cc == c - 1:
            break
            
        for i in range(4):
            nr = cr + dr[i]
            nc = cc + dc[i]
            
            if 0 <= nr < r and 0 <= nc < c:
                if grid[nr][nc] == '0' and dist[nr][nc] == -1:
                    dist[nr][nc] = dist[cr][cc] + 1
                    q.append((nr, nc))
                    
    print(dist[r - 1][c - 1])

if __name__ == "__main__":
    main()
