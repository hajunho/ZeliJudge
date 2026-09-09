import sys
from collections import deque

INF = float('inf')

def hopcroft_karp(n, m, adj):
    pair_u = [0] * (n + 1)
    pair_v = [0] * (m + 1)
    dist = [0] * (n + 1)
    
    def bfs():
        dq = deque()
        for u in range(1, n + 1):
            if pair_u[u] == 0:
                dist[u] = 0
                dq.append(u)
            else:
                dist[u] = INF
        dist[0] = INF
        
        while dq:
            u = dq.popleft()
            if dist[u] < dist[0]:
                for v in adj[u]:
                    if dist[pair_v[v]] == INF:
                        dist[pair_v[v]] = dist[u] + 1
                        dq.append(pair_v[v])
        return dist[0] != INF

    def dfs(u):
        if u != 0:
            for v in adj[u]:
                if dist[pair_v[v]] == dist[u] + 1:
                    if dfs(pair_v[v]):
                        pair_v[v] = u
                        pair_u[u] = v
                        return True
            dist[u] = INF
            return False
        return True

    matching = 0
    while bfs():
        for u in range(1, n + 1):
            if pair_u[u] == 0 and dfs(u):
                matching += 1
    return matching

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    e = int(input_data[2])
    
    adj = [[] for _ in range(n + 1)]
    idx = 3
    for _ in range(e):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj[u].append(v)
        idx += 2
        
    ans = hopcroft_karp(n, m, adj)
    print(ans)

if __name__ == '__main__':
    main()
