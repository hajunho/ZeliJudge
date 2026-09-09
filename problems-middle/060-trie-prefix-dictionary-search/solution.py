import sys

class TrieNode:
    def __init__(self):
        self.children = {}
        self.count = 0

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    Q = int(lines[1])
    idx = 2
    
    root = TrieNode()
    for _ in range(N):
        word = lines[idx]
        idx += 1
        curr = root
        curr.count += 1
        for ch in word:
            if ch not in curr.children:
                curr.children[ch] = TrieNode()
            curr = curr.children[ch]
            curr.count += 1
            
    out = []
    for _ in range(Q):
        prefix = lines[idx]
        idx += 1
        curr = root
        matched = True
        for ch in prefix:
            if ch not in curr.children:
                matched = False
                break
            curr = curr.children[ch]
        if matched:
            out.append(str(curr.count))
        else:
            out.append("0")
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
