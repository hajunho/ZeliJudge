import sys
sys.setrecursionlimit(100000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    # 노드 매핑: 1..n -> x_i (2*i), -n..-1 -> not x_i (2*|i| + 1)
    def node_id(x):
        if x > 0:
            return 2 * x
        return 2 * (-x) + 1
        
    def not_id(x):
        return x ^ 1
        
    total_nodes = 2 * n + 2
    graph = [[] for _ in range(total_nodes)]
    
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        
        nu = node_id(u)
        nv = node_id(v)
        
        # not u -> v
        graph[not_id(nu)].append(nv)
        # not v -> u
        graph[not_id(nv)].append(nu)
        
    dfsn = [0] * total_nodes
    finished = [False] * total_nodes
    scc_id = [0] * total_nodes
    stack = []
    order = 0
    scc_count = 0
    
    def dfs(u):
        nonlocal order, scc_count
        order += 1
        dfsn[u] = order
        low = order
        stack.append(u)
        
        for nxt in graph[u]:
            if dfsn[nxt] == 0:
                low = min(low, dfs(nxt))
            elif not finished[nxt]:
                low = min(low, dfsn[nxt])
                
        if low == dfsn[u]:
            scc_count += 1
            while True:
                top = stack.pop()
                finished[top] = True
                scc_id[top] = scc_count
                if top == u:
                    break
        return low

    for i in range(2, total_nodes):
        if dfsn[i] == 0:
            dfs(i)
            
    possible = True
    for i in range(1, n + 1):
        if scc_id[2 * i] == scc_id[2 * i + 1]:
            possible = False
            break
            
    print(1 if possible else 0)

if __name__ == "__main__":
    solve()
