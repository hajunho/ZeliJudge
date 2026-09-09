import sys
from collections import deque

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    n = int(lines[0])
    m = int(lines[1])
    grid = lines[2:2+n]
    
    if n == 1 and m == 1:
        print(1)
        return
        
    visited = [[[0] * 2 for _ in range(m)] for _ in range(n)]
    queue = deque([(0, 0, 0, 1)]) # r, c, broken, dist
    visited[0][0][0] = 1
    
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    while queue:
        r, c, broken, dist = queue.popleft()
        if r == n - 1 and c == m - 1:
            print(dist)
            return
            
        for d in range(4):
            nr, nc = r + dr[d], c + dc[d]
            if 0 <= nr < n and 0 <= nc < m:
                # 다음 칸이 빈칸
                if grid[nr][nc] == '0' and not visited[nr][nc][broken]:
                    visited[nr][nc][broken] = 1
                    queue.append((nr, nc, broken, dist + 1))
                # 다음 칸이 벽이고 아직 안 부쉈음
                elif grid[nr][nc] == '1' and broken == 0 and not visited[nr][nc][1]:
                    visited[nr][nc][1] = 1
                    queue.append((nr, nc, 1, dist + 1))
                    
    print(-1)

if __name__ == "__main__":
    solve()
