import sys
import heapq

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    S = int(lines[2])
    D = int(lines[3])
    
    adj = [[] for _ in range(V + 1)]
    idx = 4
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        adj[u].append((v, w))
        idx += 3
        
    INF = 10**18
    dist = [INF] * (V + 1)
    parent = [0] * (V + 1)
    
    dist[S] = 0
    pq = [(0, S)]
    
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == D:
            break
        for v, w in adj[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                parent[v] = u
                heapq.heappush(pq, (dist[v], v))
                
    if dist[D] == INF:
        print("-1")
    else:
        print(dist[D])
        # Reconstruct path
        path = []
        curr = D
        while curr != 0:
            path.append(curr)
            if curr == S:
                break
            curr = parent[curr]
        path.reverse()
        print(' '.join(map(str, path)))

if __name__ == "__main__":
    solve()
