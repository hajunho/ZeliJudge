import sys
sys.setrecursionlimit(200000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    adj = [[] for _ in range(v + 1)]
    idx = 2
    for _ in range(e):
        a = int(input_data[idx])
        b = int(input_data[idx+1])
        idx += 2
        adj[a].append(b)
        adj[b].append(a)
        
    dfsn = [0] * (v + 1)
    edge_stack = []
    bccs = []
    order = 0
    
    def dfs(u, p):
        nonlocal order
        order += 1
        dfsn[u] = order
        low = order
        
        for nxt in adj[u]:
            if nxt == p:
                continue
            if dfsn[nxt] < dfsn[u]:
                edge_stack.append((u, nxt))
            if dfsn[nxt] == 0:
                nxt_low = dfs(nxt, u)
                low = min(low, nxt_low)
                if nxt_low >= dfsn[u]:
                    cur_bcc = []
                    while True:
                        edge = edge_stack.pop()
                        cur_bcc.append(edge)
                        if edge == (u, nxt) or edge == (nxt, u):
                            break
                    bccs.append(cur_bcc)
            else:
                low = min(low, dfsn[nxt])
        return low

    for i in range(1, v + 1):
        if dfsn[i] == 0:
            dfs(i, 0)
            
    bccs_sizes = sorted([len(bcc) for bcc in bccs])
    print(len(bccs_sizes))
    print(*(bccs_sizes))

if __name__ == "__main__":
    solve()
