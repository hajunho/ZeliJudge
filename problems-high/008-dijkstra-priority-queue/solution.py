import sys
import heapq

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    start = int(input_data[2])
    
    graph = [[] for _ in range(v + 1)]
    idx = 3
    for _ in range(e):
        u = int(input_data[idx])
        to_v = int(input_data[idx+1])
        w = int(input_data[idx+2])
        idx += 3
        graph[u].append((to_v, w))
        
    INF = 10**15
    distance = [INF] * (v + 1)
    distance[start] = 0
    
    pq = [(0, start)]
    
    while pq:
        dist, cur = heapq.heappop(pq)
        if dist > distance[cur]:
            continue
            
        for nxt, weight in graph[cur]:
            cost = dist + weight
            if cost < distance[nxt]:
                distance[nxt] = cost
                heapq.heappush(pq, (cost, nxt))
                
    out = []
    for i in range(1, v + 1):
        if distance[i] == INF:
            out.append("INF")
        else:
            out.append(str(distance[i]))
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
