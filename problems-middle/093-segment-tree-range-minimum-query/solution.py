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
    
    INF = 10**18
    tree = [INF] * (4 * N)
    
    def build(node, start, end):
        if start == end:
            tree[node] = arr[start]
            return
        mid = (start + end) // 2
        build(2 * node, start, mid)
        build(2 * node + 1, mid + 1, end)
        tree[node] = min(tree[2 * node], tree[2 * node + 1])
        
    def update(node, start, end, target_idx, val):
        if start == end:
            tree[node] = val
            arr[start] = val
            return
        mid = (start + end) // 2
        if target_idx <= mid:
            update(2 * node, start, mid, target_idx, val)
        else:
            update(2 * node + 1, mid + 1, end, target_idx, val)
        tree[node] = min(tree[2 * node], tree[2 * node + 1])
        
    def query(node, start, end, l, r):
        if r < start or end < l:
            return INF
        if l <= start and end <= r:
            return tree[node]
        mid = (start + end) // 2
        p1 = query(2 * node, start, mid, l, r)
        p2 = query(2 * node + 1, mid + 1, end, l, r)
        return min(p1, p2)
        
    build(1, 0, N - 1)
    
    out = []
    for _ in range(Q):
        cmd = int(lines[idx])
        if cmd == 1:
            pos = int(lines[idx+1]) - 1
            val = int(lines[idx+2])
            update(1, 0, N - 1, pos, val)
            idx += 3
        else:
            L = int(lines[idx+1]) - 1
            R = int(lines[idx+2]) - 1
            ans = query(1, 0, N - 1, L, R)
            out.append(str(ans))
            idx += 3
            
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
