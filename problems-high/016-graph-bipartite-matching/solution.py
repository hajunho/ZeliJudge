import sys
sys.setrecursionlimit(100000)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    
    adj = [[] for _ in range(n + 1)]
    idx = 2
    for i in range(1, n + 1):
        c = int(input_data[idx])
        idx += 1
        for _ in range(c):
            room = int(input_data[idx])
            idx += 1
            adj[i].append(room)
            
    b_match = [0] * (m + 1)
    
    def dfs(u, visited):
        for v in adj[u]:
            if visited[v]:
                continue
            visited[v] = True
            if b_match[v] == 0 or dfs(b_match[v], visited):
                b_match[v] = u
                return True
        return False
        
    matches = 0
    for i in range(1, n + 1):
        visited = [False] * (m + 1)
        if dfs(i, visited):
            matches += 1
            
    print(matches)

if __name__ == "__main__":
    solve()
