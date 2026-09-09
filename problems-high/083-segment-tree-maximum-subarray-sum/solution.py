import sys

INF = float('-inf')

class Node:
    __slots__ = ['sum', 'pref', 'suff', 'ans']
    def __init__(self, val=None):
        if val is not None:
            self.sum = val
            self.pref = val
            self.suff = val
            self.ans = val
        else:
            self.sum = 0
            self.pref = INF
            self.suff = INF
            self.ans = INF

def merge(left, right):
    res = Node()
    res.sum = left.sum + right.sum
    res.pref = max(left.pref, left.sum + right.pref)
    res.suff = max(right.suff, right.sum + left.suff)
    res.ans = max(left.ans, right.ans, left.suff + right.pref)
    return res

class SegmentTree:
    def __init__(self, n, a):
        self.n = n
        self.tree = [None] * (4 * n + 4)
        self.build(1, 1, n, a)
        
    def build(self, node, s, e, a):
        if s == e:
            self.tree[node] = Node(a[s - 1])
            return
        mid = (s + e) // 2
        self.build(node * 2, s, mid, a)
        self.build(node * 2 + 1, mid + 1, e, a)
        self.tree[node] = merge(self.tree[node * 2], self.tree[node * 2 + 1])
        
    def update(self, node, s, e, idx, val):
        if s == e:
            self.tree[node] = Node(val)
            return
        mid = (s + e) // 2
        if idx <= mid:
            self.update(node * 2, s, mid, idx, val)
        else:
            self.update(node * 2 + 1, mid + 1, e, idx, val)
        self.tree[node] = merge(self.tree[node * 2], self.tree[node * 2 + 1])
        
    def query(self, node, s, e, l, r):
        if r < s or e < l:
            return None
        if l <= s and e <= r:
            return self.tree[node]
        mid = (s + e) // 2
        left = self.query(node * 2, s, mid, l, r)
        right = self.query(node * 2 + 1, mid + 1, e, l, r)
        if left is None:
            return right
        if right is None:
            return left
        return merge(left, right)

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    a = [int(x) for x in input_data[2:2+n]]
    
    seg = SegmentTree(n, a)
    
    idx = 2 + n
    out = []
    for _ in range(q):
        t = int(input_data[idx])
        if t == 1:
            i = int(input_data[idx + 1])
            x = int(input_data[idx + 2])
            idx += 3
            seg.update(1, 1, n, i, x)
        else:
            l = int(input_data[idx + 1])
            r = int(input_data[idx + 2])
            idx += 3
            res = seg.query(1, 1, n, l, r)
            out.append(str(res.ans))
            
    print('\n'.join(out))

if __name__ == '__main__':
    main()
