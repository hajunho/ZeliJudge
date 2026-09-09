import sys
from collections import deque

def bfs(start, n, adj):
    dist = [-1] * (n + 1)
    dist[start] = 0
    q = deque([start])
    
    farthest_node = start
    max_dist = 0
    
    while q:
        curr = q.popleft()
        if dist[curr] > max_dist:
            max_dist = dist[curr]
            farthest_node = curr
            
        for nxt in adj[curr]:
            if dist[nxt] == -1:
                dist[nxt] = dist[curr] + 1
                q.append(nxt)
                
    return farthest_node, max_dist

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    if v <= 1:
        print(0)
        return
        
    adj = [[] for _ in range(v + 1)]
    ptr = 1
    for _ in range(v - 1):
        u = int(input_data[ptr])
        w = int(input_data[ptr+1])
        ptr += 2
        adj[u].append(w)
        adj[w].append(u)
        
    # 1. 1번 노드에서 가장 먼 노드 u 찾기
    u, _ = bfs(1, v, adj)
    # 2. u에서 가장 먼 노드까지의 거리 구하기
    _, diameter = bfs(u, v, adj)
    
    print(diameter)

if __name__ == "__main__":
    main()
