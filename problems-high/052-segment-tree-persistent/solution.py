import sys

class Node:
    def __init__(self, count, left, right):
        self.count = count
        self.left = left
        self.right = right

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    sorted_vals = sorted(list(set(arr)))
    val_to_idx = {v: i for i, v in enumerate(sorted_vals)}
    num_vals = len(sorted_vals)
    
    def build(start, end):
        if start == end:
            return Node(0, None, None)
        mid = (start + end) // 2
        return Node(0, build(start, mid), build(mid + 1, end))
        
    def update(prev_node, start, end, target_idx):
        if start == end:
            return Node(prev_node.count + 1, None, None)
        mid = (start + end) // 2
        if target_idx <= mid:
            new_left = update(prev_node.left, start, mid, target_idx)
            return Node(prev_node.count + 1, new_left, prev_node.right)
        else:
            new_right = update(prev_node.right, mid + 1, end, target_idx)
            return Node(prev_node.count + 1, prev_node.left, new_right)
            
    roots = [build(0, num_vals - 1)]
    for x in arr:
        roots.append(update(roots[-1], 0, num_vals - 1, val_to_idx[x]))
        
    def query(node_l, node_r, start, end, k):
        if start == end:
            return sorted_vals[start]
        mid = (start + end) // 2
        left_count = node_r.left.count - node_l.left.count
        if k <= left_count:
            return query(node_l.left, node_r.left, start, mid, k)
        else:
            return query(node_l.right, node_r.right, mid + 1, end, k - left_count)

    idx = 2 + n
    out = []
    for _ in range(q):
        l = int(input_data[idx])
        r = int(input_data[idx+1])
        k = int(input_data[idx+2])
        idx += 3
        ans = query(roots[l - 1], roots[r], 0, num_vals - 1, k)
        out.append(str(ans))
        
    print("\n".join(out))

if __name__ == "__main__":
    solve()
