import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    graph = [[] for _ in range(v + 1)]
    idx = 2
    for _ in range(e):
        a = int(input_data[idx])
        b = int(input_data[idx+1])
        idx += 2
        graph[a].append(b)
        
    dfsn = [0] * (v + 1)
    finished = [False] * (v + 1)
    stack = []
    scc_list = []
    order = 0
    
    def dfs(u):
        nonlocal order
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
            cur_scc = []
            while True:
                node = stack.pop()
                finished[node] = True
                cur_scc.append(node)
                if node == u:
                    break
            cur_scc.sort()
            scc_list.append(cur_scc)
            
        return low

    for i in range(1, v + 1):
        if dfsn[i] == 0:
            dfs(i)
            
    scc_list.sort(key=lambda x: x[0])
    
    print(len(scc_list))
    for scc in scc_list:
        print(*(scc + [-1]))

if __name__ == "__main__":
    solve()
