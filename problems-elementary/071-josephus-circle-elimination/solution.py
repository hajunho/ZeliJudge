import sys
from collections import deque

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    n, k = int(parts[0]), int(parts[1])
    
    q = deque(range(1, n + 1))
    while len(q) > 1:
        for _ in range(k - 1):
            q.append(q.popleft())
        q.popleft()
        
    print(q[0])

if __name__ == "__main__":
    main()
