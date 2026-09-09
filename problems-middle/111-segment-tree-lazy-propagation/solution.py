import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    Q = int(lines[1])
    idx = 2
    arr = [int(x) for x in lines[idx:idx+N]]
    idx += N
    
    tree = [0] * (4 * N)
    lazy = [0] * (4 * N)
    
    def build(node, start, end):
        if start == end:
            tree[node] = arr[start]
            return
        mid = (start + end) // 2
        build(2 * node, start, mid)
        build(2 * node + 1, mid + 1, end)
        tree[node] = tree[2 * node] + tree[2 * node + 1]
        
    def propagate(node, start, end):
        if lazy[node] != 0:
            val = lazy[node]
            tree[node] += (end - start + 1) * val
            if start != end:
                lazy[2 * node] += val
                lazy[2 * node + 1] += val
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
        update_range(2 * node, start, mid, l, r, val)
        update_range(2 * node + 1, mid + 1, end, l, r, val)
        tree[node] = tree[2 * node] + tree[2 * node + 1]
        
    def query_sum(node, start, end, l, r):
        propagate(node, start, end)
        if r < start or end < l:
            return 0
        if l <= start and end <= r:
            return tree[node]
        mid = (start + end) // 2
        return query_sum(2 * node, start, mid, l, r) + query_sum(2 * node + 1, mid + 1, end, l, r)
        
    build(1, 0, N - 1)
    
    out = []
    for _ in range(Q):
        cmd = int(lines[idx])
        if cmd == 1:
            L = int(lines[idx+1]) - 1
            R = int(lines[idx+2]) - 1
            v = int(lines[idx+3])
            update_range(1, 0, N - 1, L, R, v)
            idx += 4
        else:
            L = int(lines[idx+1]) - 1
            R = int(lines[idx+2]) - 1
            ans = query_sum(1, 0, N - 1, L, R)
            out.append(str(ans))
            idx += 3
            
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
