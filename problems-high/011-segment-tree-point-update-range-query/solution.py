import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    k = int(input_data[2])
    
    arr = [int(x) for x in input_data[3:3+n]]
    tree = [0] * (4 * n)
    
    def build(node, start, end):
        if start == end:
            tree[node] = arr[start]
            return tree[node]
        mid = (start + end) // 2
        tree[node] = build(node * 2, start, mid) + build(node * 2 + 1, mid + 1, end)
        return tree[node]
        
    def update(node, start, end, idx, val):
        if idx < start or idx > end:
            return tree[node]
        if start == end:
            tree[node] = val
            return tree[node]
        mid = (start + end) // 2
        tree[node] = update(node * 2, start, mid, idx, val) + update(node * 2 + 1, mid + 1, end, idx, val)
        return tree[node]
        
    def query(node, start, end, l, r):
        if r < start or end < l:
            return 0
        if l <= start and end <= r:
            return tree[node]
        mid = (start + end) // 2
        return query(node * 2, start, mid, l, r) + query(node * 2 + 1, mid + 1, end, l, r)
        
    build(1, 0, n - 1)
    
    out = []
    ptr = 3 + n
    for _ in range(m + k):
        qtype = int(input_data[ptr])
        b = int(input_data[ptr+1])
        c = int(input_data[ptr+2])
        ptr += 3
        if qtype == 1:
            update(1, 0, n - 1, b - 1, c)
        else:
            ans = query(1, 0, n - 1, b - 1, c - 1)
            out.append(str(ans))
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
