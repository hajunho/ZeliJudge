import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    INF = 10**15
    dist = [[INF] * (n + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dist[i][i] = 0
        
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        w = int(input_data[idx+2])
        idx += 3
        if w < dist[u][v]:
            dist[u][v] = w
            
    for k in range(1, n + 1):
        for i in range(1, n + 1):
            if dist[i][k] == INF:
                continue
            for j in range(1, n + 1):
                cost = dist[i][k] + dist[k][j]
                if cost < dist[i][j]:
                    dist[i][j] = cost
                    
    out = []
    for i in range(1, n + 1):
        row = []
        for j in range(1, n + 1):
            if dist[i][j] == INF:
                row.append("0")
            else:
                row.append(str(dist[i][j]))
        out.append(" ".join(row))
        
    print("\n".join(out))

if __name__ == "__main__":
    solve()
