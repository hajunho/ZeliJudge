import sys

# Set recursion depth
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
        adj[v].append(u)
        idx += 2
        
    dfn = [0] * (V + 1)
    low = [0] * (V + 1)
    is_cut = [False] * (V + 1)
    timer = 0
    
    def dfs(u, is_root):
        nonlocal timer
        timer += 1
        dfn[u] = low[u] = timer
        children = 0
        
        for v in adj[u]:
            if dfn[v] == 0:
                children += 1
                dfs(v, False)
                low[u] = min(low[u], low[v])
                
                # Non-root condition: low[v] >= dfn[u]
                if not is_root and low[v] >= dfn[u]:
                    is_cut[u] = True
            else:
                low[u] = min(low[u], dfn[v])
                
        # Root condition: 2 or more children in DFS tree
        if is_root and children >= 2:
            is_cut[u] = True
            
    for i in range(1, V + 1):
        if dfn[i] == 0:
            dfs(i, True)
            
    cuts = [i for i in range(1, V + 1) if is_cut[i]]
    print(len(cuts))
    if cuts:
        print(' '.join(map(str, cuts)))

if __name__ == "__main__":
    solve()
