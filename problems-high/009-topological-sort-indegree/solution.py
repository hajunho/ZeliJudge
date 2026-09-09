import sys
from collections import deque

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    indegree = [0] * (v + 1)
    graph = [[] for _ in range(v + 1)]
    
    idx = 2
    for _ in range(e):
        a = int(input_data[idx])
        b = int(input_data[idx+1])
        idx += 2
        graph[a].append(b)
        indegree[b] += 1
        
    queue = deque([i for i in range(1, v + 1) if indegree[i] == 0])
    result = []
    
    while queue:
        cur = queue.popleft()
        result.append(cur)
        for nxt in graph[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
                
    print(*(result))

if __name__ == "__main__":
    solve()
