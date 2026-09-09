import sys
from collections import deque

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    S = int(lines[2])
    
    adj = [[] for _ in range(V + 1)]
    idx = 3
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        adj[u].append((v, w))
        idx += 3
        
    INF = 10**18
    dist = [INF] * (V + 1)
    in_queue = [False] * (V + 1)
    count = [0] * (V + 1)
    
    dist[S] = 0
    q = deque([S])
    in_queue[S] = True
    count[S] = 1
    
    has_neg_cycle = False
    while q:
        u = q.popleft()
        in_queue[u] = False
        
        for v, w in adj[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                if not in_queue[v]:
                    q.append(v)
                    in_queue[v] = True
                    count[v] += 1
                    if count[v] >= V:
                        has_neg_cycle = True
                        break
        if has_neg_cycle:
            break
            
    if has_neg_cycle:
        print("NEGATIVE CYCLE")
    else:
        out = []
        for i in range(1, V + 1):
            if dist[i] == INF:
                out.append("INF")
            else:
                out.append(str(dist[i]))
        print(' '.join(out))

if __name__ == "__main__":
    solve()
