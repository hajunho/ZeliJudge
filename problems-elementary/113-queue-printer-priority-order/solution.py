import sys
from collections import deque

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    n, m = int(parts[0]), int(parts[1])
    priorities = [int(x) for x in lines[1].split()]
    
    q = deque([(i, p) for i, p in enumerate(priorities)])
    print_count = 0
    
    while q:
        curr_idx, curr_p = q.popleft()
        if any(curr_p < other_p for other_idx, other_p in q):
            q.append((curr_idx, curr_p))
        else:
            print_count += 1
            if curr_idx == m:
                print(print_count)
                return

if __name__ == "__main__":
    main()
