import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    w = [[0] * n for _ in range(n)]
    idx = 1
    for i in range(n):
        for j in range(n):
            w[i][j] = int(input_data[idx])
            idx += 1
            
    # dp[mask][u], parent[mask][u]
    dp = [[float('inf')] * n for _ in range(1 << n)]
    parent = [[-1] * n for _ in range(1 << n)]
    
    dp[1][0] = 0
    
    for mask in range(1, 1 << n):
        for u in range(n):
            if dp[mask][u] == float('inf'):
                continue
            cur_cost = dp[mask][u]
            for v in range(n):
                if not (mask & (1 << v)):
                    nxt_mask = mask | (1 << v)
                    cost = cur_cost + w[u][v]
                    if cost < dp[nxt_mask][v]:
                        dp[nxt_mask][v] = cost
                        parent[nxt_mask][v] = u
                        
    full = (1 << n) - 1
    best_cost = float('inf')
    best_last = -1
    
    for u in range(1, n):
        cost = dp[full][u] + w[u][0]
        if cost < best_cost:
            best_cost = cost
            best_last = u
            
    # Reconstruct path
    path = [0] # returning to 0 (1-indexed: 1)
    curr = best_last
    cur_mask = full
    
    while curr != -1:
        path.append(curr)
        p = parent[cur_mask][curr]
        cur_mask ^= (1 << curr)
        curr = p
        
    path.reverse()
    print(best_cost)
    print(' '.join(str(node + 1) for node in path))

if __name__ == '__main__':
    main()
