import sys
from collections import deque

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    idx = 2
    adj = [[] for _ in range(V + 1)]
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    color = [0] * (V + 1)
    
    for i in range(1, V + 1):
        if color[i] == 0:
            color[i] = 1
            queue = deque([i])
            while queue:
                curr = queue.popleft()
                for neighbor in adj[curr]:
                    if color[neighbor] == 0:
                        color[neighbor] = 3 - color[curr]
                        queue.append(neighbor)
                    elif color[neighbor] == color[curr]:
                        print("NO")
                        return
    print("YES")

if __name__ == "__main__":
    solve()
