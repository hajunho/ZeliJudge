import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    idx = 2 + n
    
    tree_max1 = [0] * (4 * n + 4)
    tree_max2 = [-1] * (4 * n + 4)
    tree_cnt = [0] * (4 * n + 4)
    tree_sum = [0] * (4 * n + 4)
    
    def pull(node):
        lc = node * 2
        rc = node * 2 + 1
        tree_sum[node] = tree_sum[lc] + tree_sum[rc]
        if tree_max1[lc] == tree_max1[rc]:
            tree_max1[node] = tree_max1[lc]
            tree_cnt[node] = tree_cnt[lc] + tree_cnt[rc]
            tree_max2[node] = max(tree_max2[lc], tree_max2[rc])
        elif tree_max1[lc] > tree_max1[rc]:
            tree_max1[node] = tree_max1[lc]
            tree_cnt[node] = tree_cnt[lc]
            tree_max2[node] = max(tree_max2[lc], tree_max1[rc])
        else:
            tree_max1[node] = tree_max1[rc]
            tree_cnt[node] = tree_cnt[rc]
            tree_max2[node] = max(tree_max1[lc], tree_max2[rc])

    def push(node):
        for child in [node * 2, node * 2 + 1]:
            if tree_max1[node] < tree_max1[child]:
                tree_sum[child] -= (tree_max1[child] - tree_max1[node]) * tree_cnt[child]
                tree_max1[child] = tree_max1[node]

    def build(node, l, r):
        if l == r:
            v = arr[l - 1]
            tree_max1[node] = v
            tree_max2[node] = -1
            tree_cnt[node] = 1
            tree_sum[node] = v
            return
        mid = (l + r) // 2
        build(node * 2, l, mid)
        build(node * 2 + 1, mid + 1, r)
        pull(node)

    build(1, 1, n)

    def update_chmin(node, l, r, ql, qr, x):
        if ql <= l and r <= qr:
            if x >= tree_max1[node]:
                return
            if x > tree_max2[node]:
                tree_sum[node] -= (tree_max1[node] - x) * tree_cnt[node]
                tree_max1[node] = x
                return
        if l == r:
            if x < tree_max1[node]:
                tree_sum[node] = x
                tree_max1[node] = x
            return
            
        push(node)
        mid = (l + r) // 2
        if ql <= mid:
            update_chmin(node * 2, l, mid, ql, qr, x)
        if qr > mid:
            update_chmin(node * 2 + 1, mid + 1, r, ql, qr, x)
        pull(node)

    def query_sum(node, l, r, ql, qr):
        if ql <= l and r <= qr:
            return tree_sum[node]
        push(node)
        mid = (l + r) // 2
        res = 0
        if ql <= mid:
            res += query_sum(node * 2, l, mid, ql, qr)
        if qr > mid:
            res += query_sum(node * 2 + 1, mid + 1, r, ql, qr)
        return res

    out = []
    for _ in range(q):
        t = int(input_data[idx])
        if t == 1:
            ql = int(input_data[idx+1])
            qr = int(input_data[idx+2])
            x = int(input_data[idx+3])
            idx += 4
            update_chmin(1, 1, n, ql, qr, x)
        else:
            ql = int(input_data[idx+1])
            qr = int(input_data[idx+2])
            idx += 3
            out.append(str(query_sum(1, 1, n, ql, qr)))
            
    print("\n".join(out))

if __name__ == '__main__':
    solve()
