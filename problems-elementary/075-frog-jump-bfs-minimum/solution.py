import sys
from collections import deque

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    s, e = int(parts[0]), int(parts[1])
    
    if s == e:
        print(0)
        return
        
    visited = [False] * 201
    q = deque([(s, 0)])
    visited[s] = True
    
    while q:
        curr, dist = q.popleft()
        if curr == e:
            print(dist)
            return
            
        for nxt in (curr - 1, curr + 1, curr * 2):
            if 0 <= nxt <= 200 and not visited[nxt]:
                visited[nxt] = True
                q.append((nxt, dist + 1))

if __name__ == "__main__":
    main()
