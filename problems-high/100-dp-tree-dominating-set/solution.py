import sys

# Increase recursion depth
sys.setrecursionlimit(300000)

INF = float('inf')

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    if n == 1:
        print(1)
        return
        
    adj = [[] for _ in range(n + 1)]
    idx = 1
    for _ in range(n - 1):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj[u].append(v)
        adj[v].append(u)
        idx += 2
        
    # Bottom-up post-order
    order = []
    parent = [0] * (n + 1)
    visited = [False] * (n + 1)
    
    st = [1]
    visited[1] = True
    while st:
        u = st.pop()
        order.append(u)
        for v in adj[u]:
            if not visited[v]:
                visited[v] = True
                parent[v] = u
                st.append(v)
                
    dp0 = [1] * (n + 1)
    dp1 = [0] * (n + 1)
    dp2 = [0] * (n + 1)
    
    for u in reversed(order):
        sum_min = 0
        sum_dp1 = 0
        min_diff = INF
        has_child = False
        
        for v in adj[u]:
            if v != parent[u]:
                has_child = True
                dp0[u] += min(dp0[v], dp1[v], dp2[v])
                sum_dp1 += dp1[v]
                diff = dp0[v] - dp1[v]
                if diff < min_diff:
                    min_diff = diff
                    
        if not has_child:
            dp0[u] = 1
            dp1[u] = INF
            dp2[u] = 0
        else:
            dp2[u] = sum_dp1
            if min_diff <= 0:
                dp1[u] = sum_dp1 + min_diff
            else:
                dp1[u] = sum_dp1 + min_diff
                
    ans = min(dp0[1], dp1[1])
    print(ans)

if __name__ == '__main__':
    main()
