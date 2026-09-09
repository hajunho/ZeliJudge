import sys
import heapq

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    adj = [[] for _ in range(n + 1)]
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        w = int(input_data[idx + 2])
        adj[u].append((w, v))
        adj[v].append((w, u))
        idx += 3
        
    visited = [False] * (n + 1)
    visited[1] = True
    pq = []
    for w, v in adj[1]:
        heapq.heappush(pq, (w, v))
        
    cnt = 1
    total_weight = 0
    
    while pq and cnt < n:
        w, u = heapq.heappop(pq)
        if visited[u]:
            continue
        visited[u] = True
        cnt += 1
        total_weight += w
        for next_w, next_v in adj[u]:
            if not visited[next_v]:
                heapq.heappush(pq, (next_w, next_v))
                
    print(total_weight)

if __name__ == '__main__':
    main()
