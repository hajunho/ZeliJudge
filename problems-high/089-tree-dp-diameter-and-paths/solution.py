import sys

sys.setrecursionlimit(300000)

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    if n == 1:
        print(0)
        return
        
    adj = [[] for _ in range(n + 1)]
    idx = 1
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        w = int(input_data[idx + 2])
        adj[u].append((v, w))
        adj[v].append((u, w))
        idx += 3
        
    order = []
    parent = [0] * (n + 1)
    edge_w = [0] * (n + 1)
    visited = [False] * (n + 1)
    
    st = [1]
    visited[1] = True
    while st:
        u = st.pop()
        order.append(u)
        for v, w in adj[u]:
            if not visited[v]:
                visited[v] = True
                parent[v] = u
                edge_w[v] = w
                st.append(v)
                
    d1 = [0] * (n + 1)
    d2 = [0] * (n + 1)
    max_diameter = 0
    
    for u in reversed(order):
        curr_diam = d1[u] + d2[u]
        if curr_diam > max_diameter:
            max_diameter = curr_diam
            
        p = parent[u]
        if p != 0:
            cand = d1[u] + edge_w[u]
            if cand > d1[p]:
                d2[p] = d1[p]
                d1[p] = cand
            elif cand > d2[p]:
                d2[p] = cand
                
    print(max_diameter)

if __name__ == '__main__':
    main()
