import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    edges = []
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        w = int(input_data[idx+2])
        idx += 3
        edges.append((u, v, w))
        
    INF = 10**15
    dist = [INF] * (n + 1)
    dist[1] = 0
    
    has_negative_cycle = False
    
    for i in range(n):
        for u, v, w in edges:
            if dist[u] != INF and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                if i == n - 1:
                    has_negative_cycle = True
                    break
        if has_negative_cycle:
            break
            
    if has_negative_cycle:
        print(-1)
    else:
        out = []
        for i in range(2, n + 1):
            if dist[i] == INF:
                out.append("-1")
            else:
                out.append(str(dist[i]))
        print("\n".join(out))

if __name__ == "__main__":
    solve()
