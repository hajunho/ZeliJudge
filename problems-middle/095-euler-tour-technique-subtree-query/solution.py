import sys

# Set recursion depth
sys.setrecursionlimit(200000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    Q = int(lines[1])
    
    idx = 2
    vals = [0] + [int(x) for x in lines[idx:idx+N]]
    idx += N
    
    adj = [[] for _ in range(N + 1)]
    for _ in range(N - 1):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    in_time = [0] * (N + 1)
    out_time = [0] * (N + 1)
    timer = 0
    
    def dfs(u, p):
        nonlocal timer
        timer += 1
        in_time[u] = timer
        for v in adj[u]:
            if v != p:
                dfs(v, u)
        out_time[u] = timer
        
    dfs(1, 0)
    
    # Fenwick Tree on timer array (size N)
    tree = [0] * (N + 1)
    
    def update(i, delta):
        while i <= N:
            tree[i] += delta
            i += (i & -i)
            
    def query(i):
        s = 0
        while i > 0:
            s += tree[i]
            i -= (i & -i)
        return s
        
    for i in range(1, N + 1):
        update(in_time[i], vals[i])
        
    out = []
    for _ in range(Q):
        cmd = int(lines[idx])
        if cmd == 1:
            u = int(lines[idx+1])
            new_val = int(lines[idx+2])
            delta = new_val - vals[u]
            vals[u] = new_val
            update(in_time[u], delta)
            idx += 3
        else:
            u = int(lines[idx+1])
            L = in_time[u]
            R = out_time[u]
            ans = query(R) - query(L - 1)
            out.append(str(ans))
            idx += 2
            
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
