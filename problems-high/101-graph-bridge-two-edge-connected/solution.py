import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    adj = [[] for _ in range(n + 1)]
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        adj[u].append(v)
        adj[v].append(u)
        
    dfn = [0] * (n + 1)
    low = [0] * (n + 1)
    timer = 0
    bridges = set()
    
    def dfs(u, parent):
        nonlocal timer
        timer += 1
        dfn[u] = low[u] = timer
        for v in adj[u]:
            if v == parent:
                continue
            if dfn[v] != 0:
                low[u] = min(low[u], dfn[v])
            else:
                dfs(v, u)
                low[u] = min(low[u], low[v])
                if low[v] > dfn[u]:
                    bridges.add((min(u, v), max(u, v)))
                    
    for i in range(1, n + 1):
        if dfn[i] == 0:
            dfs(i, -1)
            
    # Find 2-ECC by ignoring bridge edges
    visited = [False] * (n + 1)
    comp_sizes = []
    
    for i in range(1, n + 1):
        if not visited[i]:
            visited[i] = True
            q = [i]
            cnt = 0
            while q:
                curr = q.pop()
                cnt += 1
                for nxt in adj[curr]:
                    if (min(curr, nxt), max(curr, nxt)) not in bridges and not visited[nxt]:
                        visited[nxt] = True
                        q.append(nxt)
            comp_sizes.append(cnt)
            
    comp_sizes.sort()
    print(len(bridges))
    print(len(comp_sizes))
    print(" ".join(map(str, comp_sizes)))

if __name__ == '__main__':
    solve()
