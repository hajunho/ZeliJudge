import sys
from collections import deque

INF = float('inf')

class Dinic:
    def __init__(self, n):
        self.n = n
        self.graph = [[] for _ in range(n)]
        self.level = [-1] * n
        self.ptr = [0] * n

    def add_edge(self, u, v, cap):
        self.graph[u].append([v, cap, len(self.graph[v])])
        self.graph[v].append([u, 0, len(self.graph[u]) - 1])

    def bfs(self, s, t):
        self.level = [-1] * self.n
        self.level[s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for v, cap, rev in self.graph[u]:
                if cap > 0 and self.level[v] == -1:
                    self.level[v] = self.level[u] + 1
                    q.append(v)
        return self.level[t] != -1

    def dfs(self, u, t, pushed):
        if pushed == 0 or u == t:
            return pushed
        for cid in range(self.ptr[u], len(self.graph[u])):
            self.ptr[u] = cid
            v, cap, rev = self.graph[u][cid]
            if self.level[v] == self.level[u] + 1 and cap > 0:
                tr = self.dfs(v, t, min(pushed, cap))
                if tr > 0:
                    self.graph[u][cid][1] -= tr
                    self.graph[v][rev][1] += tr
                    return tr
        return 0

    def max_flow(self, s, t):
        flow = 0
        while self.bfs(s, t):
            self.ptr = [0] * self.n
            while True:
                pushed = self.dfs(s, t, INF)
                if pushed == 0:
                    break
                flow += pushed
        return flow

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    idx = 2
    profits = [int(input_data[idx + i]) for i in range(n)]
    idx += n
    costs = [int(input_data[idx + i]) for i in range(m)]
    idx += m
    
    # Vertices: 
    # S = 0, T = n + m + 1
    # Projects: 1..n
    # Tools: n + 1 .. n + m
    total_vertices = n + m + 2
    s = 0
    t = total_vertices - 1
    dinic = Dinic(total_vertices)
    
    total_profit = sum(profits)
    for i in range(1, n + 1):
        dinic.add_edge(s, i, profits[i - 1])
        
    for j in range(1, m + 1):
        dinic.add_edge(n + j, t, costs[j - 1])
        
    for i in range(1, n + 1):
        k = int(input_data[idx])
        idx += 1
        for _ in range(k):
            tool = int(input_data[idx])
            idx += 1
            dinic.add_edge(i, n + tool, INF)
            
    min_cut = dinic.max_flow(s, t)
    print(total_profit - min_cut)

if __name__ == '__main__':
    solve()
