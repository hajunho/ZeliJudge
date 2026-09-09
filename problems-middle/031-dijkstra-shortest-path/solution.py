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
        adj[u].append((v, w))
        adj[v].append((u, w))
        idx += 3
    
    INF = float('inf')
    dist = [INF] * (V + 1)
    dist[1] = 0
    pq = [(0, 1)]
    
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                heapq.heappush(pq, (dist[v], v))
                
    ans = []
    for i in range(1, V + 1):
        if dist[i] == INF:
            ans.append("-1")
        else:
            ans.append(str(dist[i]))
    print(" ".join(ans))

if __name__ == "__main__":
    solve()
