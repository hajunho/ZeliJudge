import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    Q = int(lines[1])
    idx = 2
    
    arr = [int(lines[idx + i]) for i in range(N)]
    idx += N
    
    tree = [0] * (4 * N)
    
    def build(node, start, end):
        if start == end:
            tree[node] = arr[start]
            return
        mid = (start + end) // 2
        build(node * 2, start, mid)
        build(node * 2 + 1, mid + 1, end)
        tree[node] = tree[node * 2] + tree[node * 2 + 1]
        
    def update(node, start, end, target_idx, val):
        if target_idx < start or target_idx > end:
            return
        if start == end:
            arr[target_idx] = val
            tree[node] = val
            return
        mid = (start + end) // 2
        update(node * 2, start, mid, target_idx, val)
        update(node * 2 + 1, mid + 1, end, target_idx, val)
        tree[node] = tree[node * 2] + tree[node * 2 + 1]
        
    def query(node, start, end, left, right):
        if left > end or right < start:
            return 0
        if left <= start and end <= right:
            return tree[node]
        mid = (start + end) // 2
        return query(node * 2, start, mid, left, right) + query(node * 2 + 1, mid + 1, end, left, right)
        
    build(1, 0, N - 1)
    
    out = []
    for _ in range(Q):
        cmd = int(lines[idx])
        a = int(lines[idx+1])
        b = int(lines[idx+2])
        idx += 3
        if cmd == 1:
            # update a-th (1-indexed) to b
            update(1, 0, N - 1, a - 1, b)
        else:
            # range sum a to b (1-indexed)
            ans = query(1, 0, N - 1, a - 1, b - 1)
            out.append(str(ans))
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
