import sys
from collections import deque

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    source = 1
    sink = v
    
    capacity = {}
    flow = {}
    adj = [[] for _ in range(v + 1)]
    
    idx = 2
    for _ in range(e):
        u = int(input_data[idx])
        to_v = int(input_data[idx+1])
        c = int(input_data[idx+2])
        idx += 3
        
        adj[u].append(to_v)
        adj[to_v].append(u)
        
        capacity[(u, to_v)] = capacity.get((u, to_v), 0) + c
        if (to_v, u) not in capacity:
            capacity[(to_v, u)] = 0
            
        flow[(u, to_v)] = 0
        flow[(to_v, u)] = 0
        
    total_flow = 0
    
    while True:
        parent = [-1] * (v + 1)
        queue = deque([source])
        
        while queue and parent[sink] == -1:
            cur = queue.popleft()
            for nxt in adj[cur]:
                if capacity.get((cur, nxt), 0) - flow.get((cur, nxt), 0) > 0 and parent[nxt] == -1:
                    parent[nxt] = cur
                    queue.append(nxt)
                    if nxt == sink:
                        break
                        
        if parent[sink] == -1:
            break
            
        cur = sink
        bottle_neck = float('inf')
        while cur != source:
            prev = parent[cur]
            bottle_neck = min(bottle_neck, capacity[(prev, cur)] - flow[(prev, cur)])
            cur = prev
            
        cur = sink
        while cur != source:
            prev = parent[cur]
            flow[(prev, cur)] += bottle_neck
            flow[(cur, prev)] -= bottle_neck
            cur = prev
            
        total_flow += bottle_neck
        
    print(total_flow)

if __name__ == "__main__":
    solve()
