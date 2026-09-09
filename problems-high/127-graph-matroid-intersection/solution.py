import sys
from collections import deque

class DSU:
    def __init__(self, n):
        self.parent = list(range(n + 1))
    def find(self, i):
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]
    def union(self, i, j):
        ri = self.find(i)
        rj = self.find(j)
        if ri != rj:
            self.parent[ri] = rj
            return True
        return False

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    c = int(input_data[2])
    
    edges = []
    idx = 3
    for _ in range(e):
        u = int(input_data[idx])
        w = int(input_data[idx+1])
        col = int(input_data[idx+2])
        idx += 3
        edges.append((u, w, col))
        
    # I: set of edge indices in current independent set
    I = set()
    
    def is_graphic_independent(edge_indices):
        dsu = DSU(v)
        for ei in edge_indices:
            u, w, _ = edges[ei]
            if not dsu.union(u, w):
                return False
        return True

    def is_color_independent(edge_indices):
        used_colors = set()
        for ei in edge_indices:
            col = edges[ei][2]
            if col in used_colors:
                return False
            used_colors.add(col)
        return True

    # Matroid intersection augmenting path
    while True:
        # Source X1: y not in I s.t. I + {y} is graphic independent
        # Sink X2: y not in I s.t. I + {y} is color independent
        X1 = []
        X2 = []
        for y in range(e):
            if y not in I:
                if is_graphic_independent(I | {y}):
                    X1.append(y)
                if is_color_independent(I | {y}):
                    X2.append(y)
                    
        # Check direct intersection
        direct = set(X1) & set(X2)
        if direct:
            I.add(next(iter(direct)))
            continue
            
        # Build exchange graph
        adj = [[] for _ in range(e)]
        for y in range(e):
            if y not in I:
                for x in I:
                    # y -> x in M1 (graphic): (I - {x} + {y}) is graphic independent
                    if is_graphic_independent((I - {x}) | {y}):
                        adj[y].append(x)
                    # x -> y in M2 (color): (I - {x} + {y}) is color independent
                    if is_color_independent((I - {x}) | {y}):
                        adj[x].append(y)
                        
        # BFS from X1 to X2
        q = deque(X1)
        prev = {node: None for node in X1}
        target = None
        
        while q:
            cur = q.popleft()
            if cur in X2 and cur not in X1:
                target = cur
                break
            for nxt in adj[cur]:
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
                    
        if target is None:
            break
            
        # Reconstruct path and augment
        path = []
        curr = target
        while curr is not None:
            path.append(curr)
            curr = prev[curr]
            
        for node in path:
            if node in I:
                I.remove(node)
            else:
                I.add(node)
                
    print(len(I))

if __name__ == '__main__':
    solve()
