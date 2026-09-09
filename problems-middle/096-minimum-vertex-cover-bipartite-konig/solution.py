import sys

# Set recursion limit
sys.setrecursionlimit(100000)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    M = int(lines[1])
    E = int(lines[2])
    
    adj = [[] for _ in range(N + 1)]
    idx = 3
    for _ in range(E):
        u = int(lines[idx])
        v = int(lines[idx+1])
        adj[u].append(v)
        idx += 2
        
    # Bipartite matching (Kuhn's algorithm)
    # match_b[v] = u (u in A, v in B)
    match_b = [0] * (M + 1)
    
    def dfs(u, visited):
        for v in adj[u]:
            if not visited[v]:
                visited[v] = True
                if match_b[v] == 0 or dfs(match_b[v], visited):
                    match_b[v] = u
                    return True
        return False
        
    matching_size = 0
    for u in range(1, N + 1):
        visited = [False] * (M + 1)
        if dfs(u, visited):
            matching_size += 1
            
    # By Konig's Theorem: Min Vertex Cover == Max Bipartite Matching
    print(matching_size)

if __name__ == "__main__":
    solve()
