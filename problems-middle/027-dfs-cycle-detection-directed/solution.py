import sys
sys.setrecursionlimit(200000)

def has_cycle(u, adj, visited):
    visited[u] = 1  # 탐색 중 (Gray)
    for v in adj[u]:
        if visited[v] == 1:
            return True
        elif visited[v] == 0:
            if has_cycle(v, adj, visited):
                return True
    visited[u] = 2  # 탐색 완료 (Black)
    return False

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    v = int(input_data[0])
    e = int(input_data[1])
    
    adj = [[] for _ in range(v + 1)]
    ptr = 2
    for _ in range(e):
        src = int(input_data[ptr])
        dst = int(input_data[ptr+1])
        ptr += 2
        adj[src].append(dst)
        
    visited = [0] * (v + 1)
    cycle = False
    
    for i in range(1, v + 1):
        if visited[i] == 0:
            if has_cycle(i, adj, visited):
                cycle = True
                break
                
    print("YES" if cycle else "NO")

if __name__ == "__main__":
    main()
