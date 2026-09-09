import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    idx = 2
    edges = []
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        edges.append((u, v, w))
        idx += 3
        
    INF = 10**15
    dist = [INF] * (V + 1)
    dist[1] = 0
    
    # Relax V - 1 times
    for _ in range(V - 1):
        for u, v, w in edges:
            if dist[u] != INF and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                
    # V-th iteration: check negative cycle reachable from 1
    has_cycle = False
    for u, v, w in edges:
        if dist[u] != INF and dist[u] + w < dist[v]:
            has_cycle = True
            break
            
    if has_cycle:
        print("CYCLE")
    else:
        ans = []
        for i in range(1, V + 1):
            if dist[i] == INF:
                ans.append("-1")
            else:
                ans.append(str(dist[i]))
        print(" ".join(ans))

if __name__ == "__main__":
    solve()
