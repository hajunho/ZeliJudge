import sys
import heapq

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    V = int(lines[0])
    E = int(lines[1])
    idx = 2
    
    adj = [[] for _ in range(V + 1)]
    indegree = [0] * (V + 1)
    
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        indegree[v] += 1
        idx += 2
        
    pq = []
    for i in range(1, V + 1):
        if indegree[i] == 0:
            heapq.heappush(pq, i)
            
    result = []
    while pq:
        curr = heapq.heappop(pq)
        result.append(curr)
        for nxt in adj[curr]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(pq, nxt)
                
    if len(result) == V:
        print(" ".join(map(str, result)))
    else:
        print(-1)

if __name__ == "__main__":
    solve()
