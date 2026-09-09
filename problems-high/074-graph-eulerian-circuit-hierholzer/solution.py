import sys

sys.setrecursionlimit(300000)

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    if m == 0:
        print(1)
        return
        
    in_deg = [0] * (n + 1)
    out_deg = [0] * (n + 1)
    adj = [[] for _ in range(n + 1)]
    
    idx = 2
    start_node = 0
    for _ in range(m):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj[u].append(v)
        out_deg[u] += 1
        in_deg[v] += 1
        start_node = u
        idx += 2
        
    for i in range(1, n + 1):
        if in_deg[i] != out_deg[i]:
            print(-1)
            return
            
    circuit = []
    st = [start_node]
    
    while st:
        curr = st[-1]
        if adj[curr]:
            nxt = adj[curr].pop()
            st.append(nxt)
        else:
            circuit.append(st.pop())
            
    circuit.reverse()
    if len(circuit) != m + 1:
        print(-1)
    else:
        print(' '.join(map(str, circuit)))

if __name__ == '__main__':
    main()
