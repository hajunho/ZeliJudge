import sys

# Increase recursion depth for deep graph DFS
sys.setrecursionlimit(2000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    idx = 2
    adj = [[] for _ in range(V + 1)]
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    visited_order = [0] * (V + 1)
    order_timer = 0
    bridge_count = 0
    
    def dfs(curr, parent):
        nonlocal order_timer, bridge_count
        order_timer += 1
        visited_order[curr] = order_timer
        lowest = visited_order[curr]
        
        for nxt in adj[curr]:
            if nxt == parent:
                continue
            if visited_order[nxt] > 0:
                lowest = min(lowest, visited_order[nxt])
            else:
                sub_low = dfs(nxt, curr)
                if sub_low > visited_order[curr]:
                    bridge_count += 1
                lowest = min(lowest, sub_low)
        return lowest

    for i in range(1, V + 1):
        if visited_order[i] == 0:
            dfs(i, 0)
            
    print(bridge_count)

if __name__ == "__main__":
    solve()
