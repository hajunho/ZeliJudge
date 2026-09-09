import sys
from collections import deque

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    graph = [[] for _ in range(n + 1)]
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        w = int(input_data[idx+2])
        idx += 3
        graph[u].append((v, w))
        
    INF = 10**15
    dist = [INF] * (n + 1)
    in_queue = [False] * (n + 1)
    count = [0] * (n + 1)
    
    queue = deque([1])
    dist[1] = 0
    in_queue[1] = True
    count[1] = 1
    
    has_negative_cycle = False
    
    while queue:
        cur = queue.popleft()
        in_queue[cur] = False
        
        for nxt, weight in graph[cur]:
            if dist[cur] + weight < dist[nxt]:
                dist[nxt] = dist[cur] + weight
                if not in_queue[nxt]:
                    queue.append(nxt)
                    in_queue[nxt] = True
                    count[nxt] += 1
                    if count[nxt] >= n:
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
