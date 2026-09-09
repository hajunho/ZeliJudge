import sys

# Standard Hopcroft-Karp or DFS Bipartite Matching
def bipartite_matching(n, m, adj):
    match_v = [0] * (m + 1)
    
    def dfs(u, visited):
        for v in adj[u]:
            if not visited[v]:
                visited[v] = True
                if match_v[v] == 0 or dfs(match_v[v], visited):
                    match_v[v] = u
                    return True
        return False

    size = 0
    for u in range(1, n + 1):
        visited = [False] * (m + 1)
        if dfs(u, visited):
            size += 1
            
    return size

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    e = int(input_data[2])
    
    adj = [[] for _ in range(n + 1)]
    idx = 3
    for _ in range(e):
        u = int(input_data[idx])
        v = int(input_data[idx + 1])
        adj[u].append(v)
        idx += 2
        
    ans = bipartite_matching(n, m, adj)
    print(ans)

if __name__ == '__main__':
    main()
