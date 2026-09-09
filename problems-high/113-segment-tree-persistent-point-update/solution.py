import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    idx = 2 + n
    
    # PST Node arrays
    # Max nodes: 4N for initial + Q * log2(N) ~= 400000 + 100000 * 18 ~= 2200000
    MAX_NODES = 4 * n + q * 25
    left_child = [0] * MAX_NODES
    right_child = [0] * MAX_NODES
    tree_val = [0] * MAX_NODES
    node_cnt = 0
    
    def build(l, r):
        nonlocal node_cnt
        node_cnt += 1
        cur = node_cnt
        if l == r:
            tree_val[cur] = arr[l - 1]
            return cur
        mid = (l + r) // 2
        left_child[cur] = build(l, mid)
        right_child[cur] = build(mid + 1, r)
        tree_val[cur] = tree_val[left_child[cur]] + tree_val[right_child[cur]]
        return cur

    def update(prev, l, r, p, val):
        nonlocal node_cnt
        node_cnt += 1
        cur = node_cnt
        left_child[cur] = left_child[prev]
        right_child[cur] = right_child[prev]
        tree_val[cur] = tree_val[prev]
        
        if l == r:
            tree_val[cur] = val
            return cur
        mid = (l + r) // 2
        if p <= mid:
            left_child[cur] = update(left_child[prev], l, mid, p, val)
        else:
            right_child[cur] = update(right_child[prev], mid + 1, r, p, val)
        tree_val[cur] = tree_val[left_child[cur]] + tree_val[right_child[cur]]
        return cur

    def query(node, l, r, ql, qr):
        if ql <= l and r <= qr:
            return tree_val[node]
        mid = (l + r) // 2
        res = 0
        if ql <= mid:
            res += query(left_child[node], l, mid, ql, qr)
        if qr > mid:
            res += query(right_child[node], mid + 1, r, ql, qr)
        return res

    roots = [build(1, n)]
    out = []
    
    for _ in range(q):
        t = int(input_data[idx])
        if t == 1:
            pos = int(input_data[idx+1])
            val = int(input_data[idx+2])
            idx += 3
            new_root = update(roots[-1], 1, n, pos, val)
            roots.append(new_root)
        else:
            ver = int(input_data[idx+1])
            ql = int(input_data[idx+2])
            qr = int(input_data[idx+3])
            idx += 4
            out.append(str(query(roots[ver], 1, n, ql, qr)))
            
    print("\n".join(out))

if __name__ == '__main__':
    solve()
