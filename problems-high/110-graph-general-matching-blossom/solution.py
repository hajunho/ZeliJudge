import sys
from collections import deque

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
        
    for i in range(1, n + 1):
        adj[i].sort()
        
    match = [0] * (n + 1)
    parent = [0] * (n + 1)
    base = list(range(n + 1))
    in_blossom = [False] * (n + 1)
    
    def lca(root, u, v):
        vis = [False] * (n + 1)
        while True:
            u = base[u]
            vis[u] = True
            if u == root:
                break
            u = parent[match[u]]
        while True:
            v = base[v]
            if vis[v]:
                return v
            v = parent[match[v]]
            
    def mark_path(b, u, v, q):
        while base[u] != b:
            v = match[u]
            in_blossom[base[u]] = in_blossom[base[v]] = True
            parent[u] = v
            u = parent[v]
            q.append(v)
            
    def find_augmenting_path(root):
        nonlocal parent, in_blossom, base
        for i in range(1, n + 1):
            base[i] = i
            in_blossom[i] = False
        parent = [0] * (n + 1)
        type_node = [0] * (n + 1) # 0: unvisited, 1: outer/even, 2: inner/odd
        q = deque([root])
        type_node[root] = 1
        
        while q:
            u = q.popleft()
            for v in adj[u]:
                if base[u] == base[v] or match[u] == v:
                    continue
                if type_node[v] == 0:
                    if match[v] == 0:
                        # Augmenting path found!
                        # Backtrack from u to root, and flip matches
                        curr = u
                        nxt = v
                        while curr != 0:
                            p = match[curr]
                            match[curr] = nxt
                            match[nxt] = curr
                            curr = parent[p]
                            nxt = p
                        return True
                    else:
                        parent[v] = u
                        type_node[v] = 2
                        type_node[match[v]] = 1
                        q.append(match[v])
                elif type_node[base[v]] == 1:
                    # Blossom detected!
                    b = lca(root, u, v)
                    in_blossom = [False] * (n + 1)
                    q_new = []
                    mark_path(b, u, v, q_new)
                    mark_path(b, v, u, q_new)
                    for x in q_new:
                        q.append(x)
                    for i in range(1, n + 1):
                        if in_blossom[base[i]]:
                            base[i] = b
        return False
        
    for i in range(1, n + 1):
        if match[i] == 0:
            find_augmenting_path(i)
            
    pairs = []
    for i in range(1, n + 1):
        if match[i] > i:
            pairs.append((i, match[i]))
            
    pairs.sort()
    print(len(pairs))
    for u, v in pairs:
        print(f"{u} {v}")

if __name__ == '__main__':
    solve()
