import sys

sys.setrecursionlimit(300000)

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    adj = [[] for _ in range(n + 1)]
    rev_adj = [[] for _ in range(n + 1)]
    
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj[u].append(v)
        rev_adj[v].append(u)
        idx += 2
        
    visited = [False] * (n + 1)
    order = []
    
    for i in range(1, n + 1):
        if not visited[i]:
            st = [(i, 0)]
            visited[i] = True
            while st:
                u, edge_idx = st[-1]
                if edge_idx < len(adj[u]):
                    v = adj[u][edge_idx]
                    st[-1] = (u, edge_idx + 1)
                    if not visited[v]:
                        visited[v] = True
                        st.append((v, 0))
                else:
                    order.append(u)
                    st.pop()
                    
    visited = [False] * (n + 1)
    sccs = []
    
    while order:
        root = order.pop()
        if not visited[root]:
            comp = []
            st = [root]
            visited[root] = True
            while st:
                u = st.pop()
                comp.append(u)
                for v in rev_adj[u]:
                    if not visited[v]:
                        visited[v] = True
                        st.append(v)
            comp.sort()
            sccs.append(comp)
            
    sccs.sort(key=lambda c: c[0])
    print(len(sccs))
    for c in sccs:
        print(' '.join(map(str, c)))

if __name__ == '__main__':
    main()
