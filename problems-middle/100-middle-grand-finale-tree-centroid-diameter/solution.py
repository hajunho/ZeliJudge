import sys

# Set recursion depth
sys.setrecursionlimit(200000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    
    adj = [[] for _ in range(N + 1)]
    idx = 1
    for _ in range(N - 1):
        u = int(lines[idx])
        v = int(lines[idx+1])
        w = int(lines[idx+2])
        adj[u].append((v, w))
        adj[v].append((u, w))
        idx += 3
        
    # 1. Find Centroid
    sz = [0] * (N + 1)
    centroids = []
    
    def get_sizes(u, p):
        sz[u] = 1
        max_part = 0
        for v, w in adj[u]:
            if v != p:
                get_sizes(v, u)
                sz[u] += sz[v]
                max_part = max(max_part, sz[v])
        max_part = max(max_part, N - sz[u])
        if max_part <= N // 2:
            centroids.append(u)
            
    get_sizes(1, 0)
    best_centroid = min(centroids) if centroids else 1
    
    # 2. Find Tree Diameter (2 BFS/DFS)
    def get_farthest(start):
        dist = [-1] * (N + 1)
        dist[start] = 0
        stack = [start]
        max_d = 0
        farthest_node = start
        while stack:
            u = stack.pop()
            if dist[u] > max_d:
                max_d = dist[u]
                farthest_node = u
            for v, w in adj[u]:
                if dist[v] == -1:
                    dist[v] = dist[u] + w
                    stack.append(v)
        return farthest_node, max_d
        
    node_a, _ = get_farthest(1)
    node_b, diameter = get_farthest(node_a)
    
    print(best_centroid)
    print(diameter)

if __name__ == "__main__":
    solve()
