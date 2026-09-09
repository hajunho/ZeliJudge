import sys
from collections import deque

sys.setrecursionlimit(200000)

MOD = 1000000009
P1 = 1000003
P2 = 1000033

def find_centers(n, adj):
    deg = [len(adj[i]) for i in range(n + 1)]
    leaves = deque([i for i in range(1, n + 1) if deg[i] <= 1])
    
    remaining = n
    while remaining > 2:
        sz = len(leaves)
        remaining -= sz
        for _ in range(sz):
            u = leaves.popleft()
            for v in adj[u]:
                deg[v] -= 1
                if deg[v] == 1:
                    leaves.append(v)
    return list(leaves)

def get_hash(u, p, adj):
    child_hashes = []
    for v in adj[u]:
        if v != p:
            child_hashes.append(get_hash(v, u, adj))
            
    child_hashes.sort()
    
    h = P1
    for ch in child_hashes:
        h = (h * P2 + ch) % MOD
    h = (h + 17) % MOD
    return h

def tree_hashes(n, adj):
    centers = find_centers(n, adj)
    return {get_hash(c, 0, adj) for c in centers}

def solve_case(input_data, idx):
    n = int(input_data[idx])
    idx += 1
    
    adj1 = [[] for _ in range(n + 1)]
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj1[u].append(v)
        adj1[v].append(u)
        idx += 2
        
    adj2 = [[] for _ in range(n + 1)]
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj2[u].append(v)
        adj2[v].append(u)
        idx += 2
        
    if n == 1:
        return "YES", idx
        
    h1 = tree_hashes(n, adj1)
    h2 = tree_hashes(n, adj2)
    
    if h1 & h2:
        return "YES", idx
    else:
        return "NO", idx

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    t = int(input_data[0])
    idx = 1
    out = []
    for _ in range(t):
        res, idx = solve_case(input_data, idx)
        out.append(res)
    print('\n'.join(out))

if __name__ == '__main__':
    main()
