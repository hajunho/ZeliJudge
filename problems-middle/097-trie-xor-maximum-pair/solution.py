import sys

class TrieNode:
    def __init__(self):
        self.children = [None, None]

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    arr = [int(x) for x in lines[1:1+N]]
    
    root = TrieNode()
    
    def insert(val):
        curr = root
        for i in range(30, -1, -1):
            bit = (val >> i) & 1
            if curr.children[bit] is None:
                curr.children[bit] = TrieNode()
            curr = curr.children[bit]
            
    def query(val):
        curr = root
        max_xor = 0
        for i in range(30, -1, -1):
            bit = (val >> i) & 1
            wanted = 1 - bit
            if curr.children[wanted] is not None:
                max_xor |= (1 << i)
                curr = curr.children[wanted]
            else:
                curr = curr.children[bit]
        return max_xor
        
    ans = 0
    # Insert first element
    insert(arr[0])
    for i in range(1, N):
        ans = max(ans, query(arr[i]))
        insert(arr[i])
        
    print(ans)

if __name__ == "__main__":
    solve()
