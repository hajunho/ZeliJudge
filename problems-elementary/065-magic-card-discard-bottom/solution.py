import sys
from collections import deque

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    n = int(line)
    
    q = deque(range(1, n + 1))
    while len(q) > 1:
        q.popleft()          # 1. 맨 위 카드 버림
        top = q.popleft()    # 2. 그 다음 맨 위 카드 꺼내서
        q.append(top)        # 맨 밑으로 넣음
        
    print(q[0])

if __name__ == "__main__":
    main()
