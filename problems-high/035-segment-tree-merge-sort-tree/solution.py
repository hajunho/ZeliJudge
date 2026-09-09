import sys
from bisect import bisect_right

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    arr = [int(x) for x in input_data[1:1+n]]
    
    tree = [[] for _ in range(4 * n)]
    
    def build(node, start, end):
        if start == end:
            tree[node] = [arr[start]]
            return tree[node]
        mid = (start + end) // 2
        left_list = build(node * 2, start, mid)
        right_list = build(node * 2 + 1, mid + 1, end)
        
        # Merge two sorted lists
        merged = []
        i, j = 0, 0
        l_len, r_len = len(left_list), len(right_list)
        while i < l_len and j < r_len:
            if left_list[i] <= right_list[j]:
                merged.append(left_list[i])
                i += 1
            else:
                merged.append(right_list[j])
                j += 1
        while i < l_len:
            merged.append(left_list[i])
            i += 1
        while j < r_len:
            merged.append(right_list[j])
            j += 1
            
        tree[node] = merged
        return merged
        
    def query(node, start, end, l, r, k):
        if r < start or end < l:
            return 0
        if l <= start and end <= r:
            # count elements > k in tree[node]
            idx = bisect_right(tree[node], k)
            return len(tree[node]) - idx
        mid = (start + end) // 2
        return query(node * 2, start, mid, l, r, k) + query(node * 2 + 1, mid + 1, end, l, r, k)

    build(1, 0, n - 1)
    
    m = int(input_data[1+n])
    idx = 2 + n
    out = []
    for _ in range(m):
        ql = int(input_data[idx])
        qr = int(input_data[idx+1])
        qk = int(input_data[idx+2])
        idx += 3
        ans = query(1, 0, n - 1, ql - 1, qr - 1, qk)
        out.append(str(ans))
        
    print("\n".join(out))

if __name__ == "__main__":
    solve()
