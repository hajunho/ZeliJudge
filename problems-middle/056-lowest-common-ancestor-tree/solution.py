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
        
    depth = [-1] * (N + 1)
    parent = [0] * (N + 1)
    
    depth[1] = 0
    q = deque([1])
    while q:
        curr = q.popleft()
        for nxt in adj[curr]:
            if depth[nxt] == -1:
                depth[nxt] = depth[curr] + 1
                parent[nxt] = curr
                q.append(nxt)
                
    Q = int(lines[idx])
    idx += 1
    out = []
    for _ in range(Q):
        u = int(lines[idx])
        v = int(lines[idx+1])
        idx += 2
        
        while depth[u] > depth[v]:
            u = parent[u]
        while depth[v] > depth[u]:
            v = parent[v]
            
        while u != v:
            u = parent[u]
            v = parent[v]
            
        out.append(str(u))
    print("\n".join(out))

if __name__ == "__main__":
    solve()
