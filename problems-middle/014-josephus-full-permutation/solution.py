import sys
from collections import deque

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n, k = map(int, line.split())
    
    q = deque(range(1, n + 1))
    result = []
    
    while q:
        # K-1번 회전
        q.rotate(-(k - 1))
        # K번째 탈락
        result.append(str(q.popleft()))
        
    print(" ".join(result))

if __name__ == "__main__":
    main()
