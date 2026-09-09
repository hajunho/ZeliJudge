import sys
from collections import deque

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    R = int(lines[0])
    C = int(lines[1])
    grid = lines[2:2+R]
    
    INF = 10**9
    fire_time = [[INF] * C for _ in range(R)]
    fire_q = deque()
    
    sr, sc = -1, -1
    for r in range(R):
        for c in range(C):
            if grid[r][c] == 'F':
                fire_time[r][c] = 0
                fire_q.append((r, c))
            elif grid[r][c] == 'J':
                sr, sc = r, c
                
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    # Fire BFS
    while fire_q:
        r, c = fire_q.popleft()
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            if 0 <= nr < R and 0 <= nc < C and grid[nr][nc] != '#':
                if fire_time[nr][nc] > fire_time[r][c] + 1:
                    fire_time[nr][nc] = fire_time[r][c] + 1
                    fire_q.append((nr, nc))
                    
    # Jihoon BFS
    j_dist = [[-1] * C for _ in range(R)]
    j_dist[sr][sc] = 0
    jq = deque([(sr, sc)])
    
    ans = -1
    while jq:
        r, c = jq.popleft()
        # If boundary, escape!
        if r == 0 or r == R - 1 or c == 0 or c == C - 1:
            ans = j_dist[r][c] + 1
            break
            
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            if 0 <= nr < R and 0 <= nc < C and grid[nr][nc] == '.':
                if j_dist[nr][nc] == -1:
                    next_time = j_dist[r][c] + 1
                    if next_time < fire_time[nr][nc]:
                        j_dist[nr][nc] = next_time
                        jq.append((nr, nc))
                        
    if ans == -1:
        print("IMPOSSIBLE")
    else:
        print(ans)

if __name__ == "__main__":
    solve()
