import sys

# Increase recursion depth
sys.setrecursionlimit(200000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    
    adj = [[] for _ in range(V + 1)]
    idx = 2
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        idx += 2
        
    dfn = [0] * (V + 1)
    low = [0] * (V + 1)
    in_stack = [False] * (V + 1)
    stack = []
    timer = 0
    scc_list = []
    
    def dfs(u):
        nonlocal timer
        timer += 1
        dfn[u] = low[u] = timer
        stack.append(u)
        in_stack[u] = True
        
        for v in adj[u]:
            if dfn[v] == 0:
                dfs(v)
                low[u] = min(low[u], low[v])
            elif in_stack[v]:
                low[u] = min(low[u], dfn[v])
                
        if low[u] == dfn[u]:
            component = []
            while True:
                w = stack.pop()
                in_stack[w] = False
                component.append(w)
                if w == u:
                    break
            component.sort()
            scc_list.append(component)
            
    for i in range(1, V + 1):
        if dfn[i] == 0:
            dfs(i)
            
    # Sort SCCs by their smallest vertex
    scc_list.sort(key=lambda c: c[0])
    
    print(len(scc_list))
    for comp in scc_list:
        print(' '.join(map(str, comp)))

if __name__ == "__main__":
    solve()
