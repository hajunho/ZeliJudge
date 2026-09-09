import sys

class DSU:
    def __init__(self, n):
        self.parent = list(range(n + 1))
        self.cnt = n
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
            self.cnt -= 1
            return True
        return False

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    edges = []
    idx = 2
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx+1])
        w = int(input_data[idx+2])
        idx += 3
        edges.append((w, u, v))
        
    edges.sort()
    dsu = DSU(n)
    mst_weight = 0
    max_edge_in_mst = 0
    used_edges = 0
    
    for w, u, v in edges:
        if dsu.union(u, v):
            mst_weight += w
            if w > max_edge_in_mst:
                max_edge_in_mst = w
            used_edges += 1
            if used_edges == n - 1:
                break
                
    if used_edges == n - 1:
        print(f"{mst_weight} {max_edge_in_mst}")
    else:
        print("-1")

if __name__ == '__main__':
    solve()
