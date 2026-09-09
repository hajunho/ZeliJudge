import sys
import heapq

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    M = int(lines[1])
    Q = int(lines[2])
    
    adj = [[] for _ in range(N + 1)]
    idx = 3
    for _ in range(M):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        adj[u].append((v, w))
        adj[v].append((u, w))
        idx += 3
        
    # Dijkstra from node 1
    INF = 10**18
    dist = [INF] * (N + 1)
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
                
    # Fenwick Tree over nodes 1..N with initial weights = dist[i]
    tree = [0] * (N + 1)
    def add(i, delta):
        while i <= N:
            tree[i] += delta
            i += (i & -i)
            
    def query(i):
        s = 0
        while i > 0:
            s += tree[i]
            i -= (i & -i)
        return s
        
    for i in range(1, N + 1):
        val = dist[i] if dist[i] != INF else 0
        add(i, val)
        
    out = []
    for _ in range(Q):
        cmd = int(lines[idx])
        if cmd == 1:
            u = int(lines[idx+1])
            new_val = int(lines[idx+2])
            old_val = dist[u] if dist[u] != INF else 0
            delta = new_val - old_val
            dist[u] = new_val
            add(u, delta)
            idx += 3
        else:
            L = int(lines[idx+1])
            R = int(lines[idx+2])
            ans = query(R) - query(L - 1)
            out.append(str(ans))
            idx += 3
            
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
