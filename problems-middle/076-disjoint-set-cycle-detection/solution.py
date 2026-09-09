import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    
    parent = list(range(V + 1))
    
    def find(i):
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]
        
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i == root_j:
            return False
        parent[root_i] = root_j
        return True
        
    idx = 2
    cycle_found = False
    cycle_edge = 0
    for step in range(1, E + 1):
        u = int(lines[idx])
        v = int(lines[idx+1])
        idx += 2
        if not cycle_found:
            if not union(u, v):
                cycle_found = True
                cycle_edge = step
                
    if cycle_found:
        print(f"CYCLE {cycle_edge}")
    else:
        print("NO CYCLE")

if __name__ == "__main__":
    solve()
