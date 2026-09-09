import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    idx = 2
    
    INF = 10**9
    dist = [[INF] * (V + 1) for _ in range(V + 1)]
    for i in range(1, V + 1):
        dist[i][i] = 0
        
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        if w < dist[u][v]:
            dist[u][v] = w
        idx += 3
        
    for k in range(1, V + 1):
        for i in range(1, V + 1):
            for j in range(1, V + 1):
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]
                    
    for i in range(1, V + 1):
        row = []
        for j in range(1, V + 1):
            if dist[i][j] >= INF:
                row.append("-1")
            else:
                row.append(str(dist[i][j]))
        print(" ".join(row))

if __name__ == "__main__":
    solve()
