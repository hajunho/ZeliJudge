import sys
from collections import deque

class ACNode:
    def __init__(self):
        self.children = {}
        self.fail = None
        self.match_count = 0 # number of patterns ending here

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    K = int(lines[0])
    patterns = lines[1:1+K]
    text = lines[1+K]
    
    root = ACNode()
    
    # 1. Build Trie
    for p in patterns:
        curr = root
        for ch in p:
            if ch not in curr.children:
                curr.children[ch] = ACNode()
            curr = curr.children[ch]
        curr.match_count += 1
        
    # 2. Build Failure Links (BFS)
    q = deque()
    for ch, child in root.children.items():
        child.fail = root
        q.append(child)
        
    while q:
        curr = q.popleft()
        for ch, child in curr.children.items():
            fail_node = curr.fail
            while fail_node is not None and ch not in fail_node.children:
                fail_node = fail_node.fail
            child.fail = fail_node.children[ch] if fail_node else root
            # Accumulate matches from failure chain
            child.match_count += child.fail.match_count
            q.append(child)
            
    # 3. Search Text
    total_matches = 0
    curr = root
    for ch in text:
        while curr is not None and ch not in curr.children:
            curr = curr.fail
        if curr is None:
            curr = root
        else:
            curr = curr.children[ch]
            total_matches += curr.match_count
            
    print(total_matches)

if __name__ == "__main__":
    solve()
