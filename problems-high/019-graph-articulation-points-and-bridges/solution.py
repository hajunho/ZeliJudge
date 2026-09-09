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
        graph[b].append(a)
        
    dfsn = [0] * (v + 1)
    is_cut = [False] * (v + 1)
    order = 0
    
    def dfs(u, is_root):
        nonlocal order
        order += 1
        dfsn[u] = order
        low = order
        child_count = 0
        
        for nxt in graph[u]:
            if dfsn[nxt] == 0:
                child_count += 1
                nxt_low = dfs(nxt, False)
                low = min(low, nxt_low)
                if not is_root and nxt_low >= dfsn[u]:
                    is_cut[u] = True
            else:
                low = min(low, dfsn[nxt])
                
        if is_root and child_count >= 2:
            is_cut[u] = True
            
        return low

    for i in range(1, v + 1):
        if dfsn[i] == 0:
            dfs(i, True)
            
    cut_vertices = [i for i in range(1, v + 1) if is_cut[i]]
    print(len(cut_vertices))
    if cut_vertices:
        print(*(cut_vertices))
    else:
        print()

if __name__ == "__main__":
    solve()
