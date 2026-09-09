import sys
from collections import deque

class Node:
    __slots__ = ['children', 'fail', 'count']
    def __init__(self):
        self.children = {}
        self.fail = 0
        self.count = 0

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    k = int(input_data[0])
    patterns = input_data[1:1+k]
    text = input_data[1+k]
    
    trie = [Node()]
    
    # 1. Build Trie
    for p in patterns:
        cur = 0
        for ch in p:
            if ch not in trie[cur].children:
                trie[cur].children[ch] = len(trie)
                trie.append(Node())
            cur = trie[cur].children[ch]
        trie[cur].count += 1
        
    # 2. Build Failure Links (BFS)
    q = deque()
    for ch, nxt in trie[0].children.items():
        trie[nxt].fail = 0
        q.append(nxt)
        
    while q:
        u = q.popleft()
        trie[u].count += trie[trie[u].fail].count
        for ch, v in trie[u].children.items():
            f = trie[u].fail
            while f != 0 and ch not in trie[f].children:
                f = trie[f].fail
            if ch in trie[f].children:
                f = trie[f].children[ch]
            trie[v].fail = f
            q.append(v)
            
    # 3. Query Text
    ans = 0
    cur = 0
    for ch in text:
        while cur != 0 and ch not in trie[cur].children:
            cur = trie[cur].fail
        if ch in trie[cur].children:
            cur = trie[cur].children[ch]
        ans += trie[cur].count
        
    print(ans)

if __name__ == '__main__':
    solve()
