import sys
from collections import deque

class Edge:
    def __init__(self, to, cap, cost, rev):
        self.to = to
        self.cap = cap
        self.cost = cost
        self.flow = 0
        self.rev = rev

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    source = 1
    sink = v
    adj = [[] for _ in range(v + 1)]
    
    idx = 2
    for _ in range(e):
        u = int(input_data[idx])
        to_v = int(input_data[idx+1])
        c = int(input_data[idx+2])
        d = int(input_data[idx+3])
        idx += 4
        
        e1 = Edge(to_v, c, d, None)
        e2 = Edge(u, 0, -d, e1)
        e1.rev = e2
        adj[u].append(e1)
        adj[to_v].append(e2)
        
    total_flow = 0
    total_cost = 0
    INF = float('inf')
    
    while True:
        dist = [INF] * (v + 1)
        prev_node = [-1] * (v + 1)
        prev_edge = [None] * (v + 1)
        in_queue = [False] * (v + 1)
        
        queue = deque([source])
        dist[source] = 0
        in_queue[source] = True
        
        while queue:
            cur = queue.popleft()
            in_queue[cur] = False
            
            for edge in adj[cur]:
                if edge.cap - edge.flow > 0 and dist[cur] + edge.cost < dist[edge.to]:
                    dist[edge.to] = dist[cur] + edge.cost
                    prev_node[edge.to] = cur
                    prev_edge[edge.to] = edge
                    if not in_queue[edge.to]:
                        queue.append(edge.to)
                        in_queue[edge.to] = True
                        
        if dist[sink] == INF:
            break
            
        cur = sink
        pushed = INF
        while cur != source:
            pushed = min(pushed, prev_edge[cur].cap - prev_edge[cur].flow)
            cur = prev_node[cur]
            
        cur = sink
        while cur != source:
            prev_edge[cur].flow += pushed
            prev_edge[cur].rev.flow -= pushed
            cur = prev_node[cur]
            
        total_flow += pushed
        total_cost += pushed * dist[sink]
        
    print(f"{total_flow} {total_cost}")

if __name__ == "__main__":
    solve()
