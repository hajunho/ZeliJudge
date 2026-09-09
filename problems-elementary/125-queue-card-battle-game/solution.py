import sys
from collections import deque

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n, m = map(int, lines[0].split())
    q_a = deque(map(int, lines[1].split()))
    q_b = deque(map(int, lines[2].split()))
    
    for _ in range(m):
        if not q_a or not q_b:
            break
        card_a = q_a.popleft()
        card_b = q_b.popleft()
        
        if card_a > card_b:
            q_a.append(card_a)
            q_a.append(card_b)
        elif card_a < card_b:
            q_b.append(card_b)
            q_b.append(card_a)
        else:
            q_a.append(card_a)
            q_b.append(card_b)
            
    print(f"{len(q_a)} {len(q_b)}")

if __name__ == "__main__":
    main()
