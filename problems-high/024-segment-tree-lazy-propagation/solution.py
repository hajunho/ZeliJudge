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
    lazy = [0] * (4 * n)
    
    def build(node, start, end):
        if start == end:
            tree[node] = arr[start]
            return tree[node]
        mid = (start + end) // 2
        tree[node] = build(node * 2, start, mid) + build(node * 2 + 1, mid + 1, end)
        return tree[node]
        
    def propagate(node, start, end):
        if lazy[node] != 0:
            tree[node] += (end - start + 1) * lazy[node]
            if start != end:
                lazy[node * 2] += lazy[node]
                lazy[node * 2 + 1] += lazy[node]
            lazy[node] = 0
            
    def update_range(node, start, end, l, r, val):
        propagate(node, start, end)
        if r < start or end < l:
            return
        if l <= start and end <= r:
            lazy[node] += val
            propagate(node, start, end)
            return
        mid = (start + end) // 2
        update_range(node * 2, start, mid, l, r, val)
        update_range(node * 2 + 1, mid + 1, end, l, r, val)
        tree[node] = tree[node * 2] + tree[node * 2 + 1]
        
    def query(node, start, end, l, r):
        propagate(node, start, end)
        if r < start or end < l:
            return 0
        if l <= start and end <= r:
            return tree[node]
        mid = (start + end) // 2
        return query(node * 2, start, mid, l, r) + query(node * 2 + 1, mid + 1, end, l, r)

    build(1, 0, n - 1)
    
    ptr = 3 + n
    out = []
    for _ in range(m + k):
        qtype = int(input_data[ptr])
        if qtype == 1:
            b = int(input_data[ptr+1])
            c = int(input_data[ptr+2])
            d = int(input_data[ptr+3])
            ptr += 4
            update_range(1, 0, n - 1, b - 1, c - 1, d)
        else:
            b = int(input_data[ptr+1])
            c = int(input_data[ptr+2])
            ptr += 3
            ans = query(1, 0, n - 1, b - 1, c - 1)
            out.append(str(ans))
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
