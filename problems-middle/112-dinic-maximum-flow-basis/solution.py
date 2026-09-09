import sys
from collections import deque

class Edge:
    def __init__(self, to, cap, rev):
        self.to = to
        self.cap = cap
        self.rev = rev

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    S = int(lines[2])
    T = int(lines[3])
    
    adj = [[] for _ in range(V + 1)]
    
    def add_edge(u, v, cap):
        e1 = Edge(v, cap, len(adj[v]))
        e2 = Edge(u, 0, len(adj[u]))
        adj[u].append(e1)
        adj[v].append(e2)
        
    idx = 4
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        c = int(lines[idx+2])
        add_edge(u, v, c)
        idx += 3
        
    level = [-1] * (V + 1)
    ptr = [0] * (V + 1)
    
    def bfs():
        for i in range(V + 1):
            level[i] = -1
        level[S] = 0
        q = deque([S])
        while q:
            u = q.popleft()
            for edge in adj[u]:
                if edge.cap > 0 and level[edge.to] == -1:
                    level[edge.to] = level[u] + 1
                    q.append(edge.to)
        return level[T] != -1
        
    def dfs(u, pushed):
        if pushed == 0 or u == T:
            return pushed
        for cid in range(ptr[u], len(adj[u])):
            ptr[u] = cid
            edge = adj[u][cid]
            tr = edge.to
            if level[tr] != level[u] + 1 or edge.cap == 0:
                continue
            tr_pushed = dfs(tr, min(pushed, edge.cap))
            if tr_pushed == 0:
                continue
            edge.cap -= tr_pushed
            adj[tr][edge.rev].cap += tr_pushed
            return tr_pushed
        return 0
        
    max_flow = 0
    INF = 10**18
    while bfs():
        for i in range(V + 1):
            ptr[i] = 0
        while True:
            pushed = dfs(S, INF)
            if pushed == 0:
                break
            max_flow += pushed
            
    print(max_flow)

if __name__ == "__main__":
    solve()
