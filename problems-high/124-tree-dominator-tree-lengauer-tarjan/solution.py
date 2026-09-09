import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    root = int(input_data[2])
    
    adj = [[] for _ in range(n + 1)]
    radj = [[] for _ in range(n + 1)]
    idx = 3
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        adj[u].append(v)
        radj[v].append(u)
        
    dfn = [0] * (n + 1)
    rev_dfn = [0] * (n + 1)
    parent = [0] * (n + 1)
    timer = 0
    
    # DFS
    stack = [root]
    # Iterative DFS for order
    q = []
    call_stack = [(root, 0)]
    timer += 1
    dfn[root] = timer
    rev_dfn[timer] = root
    
    while call_stack:
        u, edge_idx = call_stack[-1]
        if edge_idx < len(adj[u]):
            v = adj[u][edge_idx]
            call_stack[-1] = (u, edge_idx + 1)
            if dfn[v] == 0:
                timer += 1
                dfn[v] = timer
                rev_dfn[timer] = v
                parent[v] = u
                call_stack.append((v, 0))
        else:
            call_stack.pop()
            
    # Lengauer-Tarjan
    sdom = list(range(n + 1))
    idom = [0] * (n + 1)
    dsu_parent = list(range(n + 1))
    dsu_min = list(range(n + 1))
    bucket = [[] for _ in range(n + 1)]
    
    def dsu_find(u):
        if dsu_parent[u] == u:
            return u
        root = dsu_find(dsu_parent[u])
        if dfn[sdom[dsu_min[dsu_parent[u]]]] < dfn[sdom[dsu_min[u]]]:
            dsu_min[u] = dsu_min[dsu_parent[u]]
        dsu_parent[u] = root
        return root

    for i in range(timer, 1, -1):
        w = rev_dfn[i]
        for v in radj[w]:
            if dfn[v] == 0:
                continue
            if dfn[v] < dfn[w]:
                k = v
            else:
                dsu_find(v)
                k = sdom[dsu_min[v]]
            if dfn[k] < dfn[sdom[w]]:
                sdom[w] = k
        bucket[sdom[w]].append(w)
        dsu_parent[w] = parent[w]
        
        for v in bucket[parent[w]]:
            dsu_find(v)
            u = dsu_min[v]
            idom[v] = u if sdom[u] == sdom[v] else parent[w] # temporary
        bucket[parent[w]].clear()
        
    for i in range(2, timer + 1):
        w = rev_dfn[i]
        if idom[w] != sdom[w]:
            idom[w] = idom[idom[w]]
            
    ans = [idom[i] for i in range(2, n + 1)]
    print(" ".join(map(str, ans)))

if __name__ == '__main__':
    solve()
