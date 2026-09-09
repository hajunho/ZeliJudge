import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    R = int(lines[1])
    
    visited = [False] * (N + 1)
    path = []
    
    def dfs(depth):
        if depth == R:
            print(" ".join(map(str, path)))
            return
        for i in range(1, N + 1):
            if not visited[i]:
                visited[i] = True
                path.append(i)
                dfs(depth + 1)
                path.pop()
                visited[i] = False
                
    dfs(0)

if __name__ == "__main__":
    solve()
