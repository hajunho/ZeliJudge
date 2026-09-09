import sys
from collections import deque

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    adj = [[] for _ in range(N + 1)]
    for _ in range(N - 1):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    # BFS to establish parent and topological order
    parent = [0] * (N + 1)
    order = []
    visited = [False] * (N + 1)
    
    visited[1] = True
    q = deque([1])
    while q:
        curr = q.popleft()
        order.append(curr)
        for nxt in adj[curr]:
            if not visited[nxt]:
                visited[nxt] = True
                parent[nxt] = curr
                q.append(nxt)
                
    # DP from bottom up (reversed BFS order)
    size = [1] * (N + 1)
    for u in reversed(order):
        p = parent[u]
        if p != 0:
            size[p] += size[u]
            
    print(" ".join(str(size[i]) for i in range(1, N + 1)))

if __name__ == "__main__":
    solve()
