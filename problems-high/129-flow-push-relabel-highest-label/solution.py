import sys
from collections import deque
import heapq

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    s = int(input_data[2])
    t = int(input_data[3])
    
    idx = 4
    edge_list = []
    adj = [[] for _ in range(n + 1)]
    
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        c = int(input_data[idx+2])
        idx += 3
        
        e_idx = len(edge_list)
        # u -> v
        edge_list.append([v, c, 0, e_idx + 1])
        adj[u].append(e_idx)
        # v -> u
        edge_list.append([u, 0, 0, e_idx])
        adj[v].append(e_idx + 1)
        
    height = [0] * (n + 1)
    excess = [0] * (n + 1)
    height[s] = n
    excess[s] = float('inf')
    
    # Push from s
    for e_idx in adj[s]:
        v, cap, flow, rev = edge_list[e_idx]
        if cap > 0:
            edge_list[e_idx][2] += cap
            edge_list[rev][2] -= cap
            excess[v] += cap
            excess[s] -= cap
            
    # Priority queue for highest label: (-height[u], u)
    pq = []
    in_pq = [False] * (n + 1)
    for i in range(1, n + 1):
        if i != s and i != t and excess[i] > 0:
            heapq.heappush(pq, (-height[i], i))
            in_pq[i] = True
            
    while pq:
        _, u = heapq.heappop(pq)
        in_pq[u] = False
        if excess[u] == 0 or u == s or u == t:
            continue
            
        # Try pushing
        pushed = False
        for e_idx in adj[u]:
            v, cap, flow, rev = edge_list[e_idx]
            rem = cap - flow
            if rem > 0 and height[u] == height[v] + 1:
                send = min(excess[u], rem)
                edge_list[e_idx][2] += send
                edge_list[rev][2] -= send
                excess[u] -= send
                excess[v] += send
                if v != s and v != t and not in_pq[v] and excess[v] > 0:
                    heapq.heappush(pq, (-height[v], v))
                    in_pq[v] = True
                if excess[u] == 0:
                    pushed = True
                    break
                    
        if not pushed and excess[u] > 0:
            # Relabel u
            min_h = float('inf')
            for e_idx in adj[u]:
                v, cap, flow, rev = edge_list[e_idx]
                if cap - flow > 0:
                    min_h = min(min_h, height[v])
            if min_h < float('inf'):
                height[u] = min_h + 1
                heapq.heappush(pq, (-height[u], u))
                in_pq[u] = True

    print(excess[t])

if __name__ == '__main__':
    solve()
