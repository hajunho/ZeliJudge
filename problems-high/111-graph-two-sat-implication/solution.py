import sys
sys.setrecursionlimit(300000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    # 2*n vertices: 
    # x_i: i, not x_i: i + n  (1 <= i <= n)
    # neg(u): u + n if u <= n else u - n
    def node(lit):
        return lit if lit > 0 else (-lit) + n
    def neg(u):
        return u + n if u <= n else u - n

    adj = [[] for _ in range(2 * n + 1)]
    idx = 2
    for _ in range(m):
        l1 = int(input_data[idx])
        l2 = int(input_data[idx+1])
        idx += 2
        u1 = node(l1)
        u2 = node(l2)
        # not u1 => u2, not u2 => u1
        adj[neg(u1)].append(u2)
        adj[neg(u2)].append(u1)

    dfn = [0] * (2 * n + 1)
    low = [0] * (2 * n + 1)
    scc = [0] * (2 * n + 1)
    in_stack = [False] * (2 * n + 1)
    stack = []
    timer = 0
    scc_cnt = 0

    # Iterative Tarjan to avoid recursion depth issues
    for i in range(1, 2 * n + 1):
        if dfn[i] != 0:
            continue
        call_stack = [(i, 0)]
        while call_stack:
            u, edge_idx = call_stack[-1]
            if edge_idx == 0:
                timer += 1
                dfn[u] = low[u] = timer
                stack.append(u)
                in_stack[u] = True
            
            advanced = False
            while edge_idx < len(adj[u]):
                v = adj[u][edge_idx]
                edge_idx += 1
                call_stack[-1] = (u, edge_idx)
                if dfn[v] == 0:
                    call_stack.append((v, 0))
                    advanced = True
                    break
                elif in_stack[v]:
                    low[u] = min(low[u], dfn[v])
            if advanced:
                continue
                
            # Pop finished node
            call_stack.pop()
            if call_stack:
                pu = call_stack[-1][0]
                low[pu] = min(low[pu], low[u])
                
            if low[u] == dfn[u]:
                scc_cnt += 1
                while True:
                    w = stack.pop()
                    in_stack[w] = False
                    scc[w] = scc_cnt
                    if w == u:
                        break

    ans = [0] * (n + 1)
    for i in range(1, n + 1):
        if scc[i] == scc[i + n]:
            print(0)
            return
        # If scc[i] < scc[i + n], then i is reached after i+n in topological order => True
        ans[i] = 1 if scc[i] < scc[i + n] else 0

    print(1)
    print(" ".join(str(ans[i]) for i in range(1, n + 1)))

if __name__ == '__main__':
    solve()
