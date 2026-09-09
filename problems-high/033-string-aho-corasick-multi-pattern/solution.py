import sys
from collections import deque

class Node:
    def __init__(self):
        self.children = {}
        self.fail = None
        self.output_count = 0

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    n = int(lines[0])
    patterns = lines[1:1+n]
    text = lines[1+n] if len(lines) > 1+n else ""
    
    root = Node()
    for p in patterns:
        cur = root
        for ch in p:
            if ch not in cur.children:
                cur.children[ch] = Node()
            cur = cur.children[ch]
        cur.output_count += 1
        
    # BFS 실패 링크 연결
    queue = deque()
    root.fail = root
    for ch, child in root.children.items():
        child.fail = root
        queue.append(child)
        
    while queue:
        cur = queue.popleft()
        for ch, child in cur.children.items():
            f = cur.fail
            while f != root and ch not in f.children:
                f = f.fail
            if ch in f.children:
                f = f.children[ch]
            child.fail = f
            child.output_count += f.output_count
            queue.append(child)
            
    # 본문 탐색
    total_matches = 0
    cur = root
    for ch in text:
        while cur != root and ch not in cur.children:
            cur = cur.fail
        if ch in cur.children:
            cur = cur.children[ch]
        total_matches += cur.output_count
        
    print(total_matches)

if __name__ == "__main__":
    solve()
