import sys

# Increase recursion depth
sys.setrecursionlimit(200000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    
    # Store edges and used flags
    # adj[u] = list of (v, edge_idx)
    adj = [[] for _ in range(V + 1)]
    degrees = [0] * (V + 1)
    
    idx = 2
    for i in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append((v, i))
        adj[v].append((u, i))
        degrees[u] += 1
        degrees[v] += 1
        idx += 2
        
    # Check Eulerian Circuit condition: all degrees must be even
    for i in range(1, V + 1):
        if degrees[i] % 2 != 0:
            print("NO")
            return
            
    used = [False] * E
    circuit = []
    
    # Hierholzer's Algorithm (Iterative with stack)
    stack = [1]
    curr_edge_idx = [0] * (V + 1)
    
    while stack:
        u = stack[-1]
        found = False
        while curr_edge_idx[u] < len(adj[u]):
            v, eid = adj[u][curr_edge_idx[u]]
            curr_edge_idx[u] += 1
            if not used[eid]:
                used[eid] = True
                stack.append(v)
                found = True
                break
        if not found:
            circuit.append(stack.pop())
            
    if len(circuit) != E + 1:
        print("NO")
    else:
        print("YES")
        circuit.reverse()
        print(' '.join(map(str, circuit)))

if __name__ == "__main__":
    solve()
