import sys

# Increase recursion depth for deep trees
sys.setrecursionlimit(300000)

MOD = 1000000007

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    w = [0] + [int(x) % MOD for x in input_data[2:2+n]]
    
    idx = 2 + n
    adj = [[] for _ in range(n + 1)]
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    # Euler Tour with stack to avoid deep recursion limit issues
    tin = [0] * (n + 1)
    tout = [0] * (n + 1)
    flat_w = [0] * (n + 1)
    timer = 0
    
    # iterative DFS
    st = [(1, 0, False)]
    while st:
        u, p, visited = st.pop()
        if not visited:
            timer += 1
            tin[u] = timer
            flat_w[timer] = w[u]
            st.append((u, p, True))
            for v in adj[u]:
                if v != p:
                    st.append((v, u, False))
        else:
            tout[u] = timer
            
    # Segment Tree with Lazy Propagation
    tree = [0] * (4 * n + 4)
    lazy = [0] * (4 * n + 4)
    
    def build(node, s, e):
        if s == e:
            tree[node] = flat_w[s]
            return
        mid = (s + e) // 2
        build(node * 2, s, mid)
        build(node * 2 + 1, mid + 1, e)
        tree[node] = (tree[node * 2] + tree[node * 2 + 1]) % MOD

    build(1, 1, n)
    
    def push(node, s, e):
        if lazy[node] != 0:
            mid = (s + e) // 2
            lz = lazy[node]
            # left child
            tree[node * 2] = (tree[node * 2] + lz * (mid - s + 1)) % MOD
            lazy[node * 2] = (lazy[node * 2] + lz) % MOD
            # right child
            tree[node * 2 + 1] = (tree[node * 2 + 1] + lz * (e - mid)) % MOD
            lazy[node * 2 + 1] = (lazy[node * 2 + 1] + lz) % MOD
            lazy[node] = 0

    def update(node, s, e, l, r, val):
        if r < s or e < l:
            return
        if l <= s and e <= r:
            tree[node] = (tree[node] + val * (e - s + 1)) % MOD
            lazy[node] = (lazy[node] + val) % MOD
            return
        push(node, s, e)
        mid = (s + e) // 2
        update(node * 2, s, mid, l, r, val)
        update(node * 2 + 1, mid + 1, e, l, r, val)
        tree[node] = (tree[node * 2] + tree[node * 2 + 1]) % MOD

    def query(node, s, e, l, r):
        if r < s or e < l:
            return 0
        if l <= s and e <= r:
            return tree[node]
        push(node, s, e)
        mid = (s + e) // 2
        return (query(node * 2, s, mid, l, r) + query(node * 2 + 1, mid + 1, e, l, r)) % MOD

    out = []
    for _ in range(q):
        t = int(input_data[idx])
        if t == 1:
            u = int(input_data[idx + 1])
            x = int(input_data[idx + 2]) % MOD
            idx += 3
            update(1, 1, n, tin[u], tout[u], x)
        else:
            u = int(input_data[idx + 1])
            idx += 2
            res = query(1, 1, n, tin[u], tout[u])
            out.append(str(res))
            
    print('\n'.join(out))

if __name__ == '__main__':
    main()
