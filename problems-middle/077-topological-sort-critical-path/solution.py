import sys
from collections import deque

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    M = int(lines[1])
    
    times = [0] + [int(x) for x in lines[2:2+N]]
    idx = 2 + N
    
    adj = [[] for _ in range(N + 1)]
    indegree = [0] * (N + 1)
    
    for _ in range(M):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        indegree[v] += 1
        idx += 2
        
    dp = [0] * (N + 1)
    q = deque()
    for i in range(1, N + 1):
        if indegree[i] == 0:
            dp[i] = times[i]
            q.append(i)
            
    while q:
        u = q.popleft()
        for v in adj[u]:
            if dp[u] + times[v] > dp[v]:
                dp[v] = dp[u] + times[v]
            indegree[v] -= 1
            if indegree[v] == 0:
                q.append(v)
                
    total_time = max(dp)
    print(total_time)
    print(' '.join(map(str, dp[1:N+1])))

if __name__ == "__main__":
    solve()
