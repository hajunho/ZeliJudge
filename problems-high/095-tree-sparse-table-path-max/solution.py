import sys

# Increase recursion depth
sys.setrecursionlimit(300000)

MAX_LOG = 18

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    
    adj = [[] for _ in range(n + 1)]
    idx = 2
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        w = int(input_data[idx + 2])
        adj[u].append((v, w))
        adj[v].append((u, w))
        idx += 3
        
    depth = [0] * (n + 1)
    up = [[0] * (n + 1) for _ in range(MAX_LOG)]
    max_edge = [[0] * (n + 1) for _ in range(MAX_LOG)]
    
    # BFS to setup tree parent and depth
    st = [(1, 0, 0)]
    visited = [False] * (n + 1)
    visited[1] = True
    
    while st:
        u, p, d = st.pop()
        depth[u] = d
        for v, w in adj[u]:
            if not visited[v]:
                visited[v] = True
                up[0][v] = u
                max_edge[0][v] = w
                st.append((v, u, d + 1))
                
    for k in range(1, MAX_LOG):
        for v in range(1, n + 1):
            p = up[k - 1][v]
            up[k][v] = up[k - 1][p]
            max_edge[k][v] = max(max_edge[k - 1][v], max_edge[k - 1][p])
            
    def query(u, v):
        if u == v:
            return 0
        ans = 0
        if depth[u] < depth[v]:
            u, v = v, u
            
        diff = depth[u] - depth[v]
        for k in range(MAX_LOG - 1, -1, -1):
            if (diff >> k) & 1:
                ans = max(ans, max_edge[k][u])
                u = up[k][u]
                
        if u == v:
            return ans
            
        for k in range(MAX_LOG - 1, -1, -1):
            if up[k][u] != up[k][v]:
                ans = max(ans, max_edge[k][u], max_edge[k][v])
                u = up[k][u]
                v = up[k][v]
                
        ans = max(ans, max_edge[0][u], max_edge[0][v])
        return ans

    out = []
    for _ in range(q):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        idx += 2
        out.append(str(query(u, v)))
        
    print('\n'.join(out))

if __name__ == '__main__':
    main()
