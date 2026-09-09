import sys
import heapq

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
        w = int(lines[idx+2])
        adj[u].append((w, v))
        adj[v].append((w, u))
        idx += 3
        
    if V == 1:
        print(0)
        return
        
    visited = [False] * (V + 1)
    pq = [(0, 1)]
    total_cost = 0
    count = 0
    
    while pq and count < V:
        w, u = heapq.heappop(pq)
        if visited[u]:
            continue
        visited[u] = True
        total_cost += w
        count += 1
        for nw, nv in adj[u]:
            if not visited[nv]:
                heapq.heappush(pq, (nw, nv))
                
    if count == V:
        print(total_cost)
    else:
        print(-1)

if __name__ == "__main__":
    solve()
