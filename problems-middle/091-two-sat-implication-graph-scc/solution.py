import sys

# Increase recursion depth
sys.setrecursionlimit(200000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    M = int(lines[1])
    
    # Mapping: variable i (1..N)
    # +i -> 2 * i
    # -i -> 2 * i + 1
    def get_node(x):
        if x > 0:
            return 2 * x
        else:
            return 2 * (-x) + 1
            
    def get_neg(u):
        return u ^ 1
        
    adj = [[] for _ in range(2 * N + 2)]
    idx = 2
    for _ in range(M):
        u = int(lines[idx])
        v = int(lines[idx+1])
        idx += 2
        
        nu = get_node(u)
        nv = get_node(v)
        # (u or v) <=> (~u -> v) and (~v -> u)
        adj[get_neg(nu)].append(nv)
        adj[get_neg(nv)].append(nu)
        
    dfn = [0] * (2 * N + 2)
    low = [0] * (2 * N + 2)
    scc = [0] * (2 * N + 2)
    in_stack = [False] * (2 * N + 2)
    stack = []
    timer = 0
    scc_cnt = 0
    
    def dfs(u):
        nonlocal timer, scc_cnt
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
            scc_cnt += 1
            while True:
                w = stack.pop()
                in_stack[w] = False
                scc[w] = scc_cnt
                if w == u:
                    break
                    
    for i in range(2, 2 * N + 2):
        if dfn[i] == 0:
            dfs(i)
            
    possible = True
    ans = [0] * (N + 1)
    for i in range(1, N + 1):
        pos_node = 2 * i
        neg_node = 2 * i + 1
        if scc[pos_node] == scc[neg_node]:
            possible = False
            break
        # In Tarjan's SCC, smaller SCC id means topologically later (reverse postorder)
        # If scc[pos_node] < scc[neg_node], pos_node is topologically later -> True (1)
        if scc[pos_node] < scc[neg_node]:
            ans[i] = 1
        else:
            ans[i] = 0
            
    if not possible:
        print(0)
    else:
        print(1)
        print(' '.join(map(str, ans[1:N+1])))

if __name__ == "__main__":
    solve()
