import sys
from collections import deque
sys.setrecursionlimit(10000)

class Edge:
    def __init__(self, to, cap, flow, rev):
        self.to = to
        self.cap = cap
        self.flow = flow
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
        idx += 3
        
        e1 = Edge(to_v, c, 0, None)
        e2 = Edge(u, 0, 0, e1)
        e1.rev = e2
        adj[u].append(e1)
        adj[to_v].append(e2)
        
    level = [-1] * (v + 1)
    work = [0] * (v + 1)
    
    def bfs():
        for i in range(1, v + 1):
            level[i] = -1
        level[source] = 0
        q = deque([source])
        while q:
            cur = q.popleft()
            for edge in adj[cur]:
                if edge.cap - edge.flow > 0 and level[edge.to] == -1:
                    level[edge.to] = level[cur] + 1
                    q.append(edge.to)
        return level[sink] != -1
        
    def dfs(cur, flow):
        if cur == sink:
            return flow
        for i in range(work[cur], len(adj[cur])):
            work[cur] = i
            edge = adj[cur][i]
            if level[edge.to] == level[cur] + 1 and edge.cap - edge.flow > 0:
                pushed = dfs(edge.to, min(flow, edge.cap - edge.flow))
                if pushed > 0:
                    edge.flow += pushed
                    edge.rev.flow -= pushed
                    return pushed
        return 0

    total_flow = 0
    while bfs():
        for i in range(1, v + 1):
            work[i] = 0
        while True:
            pushed = dfs(source, float('inf'))
            if pushed == 0:
                break
            total_flow += pushed
            
    print(total_flow)

if __name__ == "__main__":
    solve()
