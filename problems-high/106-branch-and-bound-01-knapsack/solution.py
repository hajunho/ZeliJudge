import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    w_cap = int(input_data[1])
    
    items = []
    idx = 2
    for _ in range(n):
        w = int(input_data[idx])
        v = int(input_data[idx+1])
        idx += 2
        items.append((w, v))
        
    # Sort by value per weight descending
    # Tie-breaking by weight descending
    items.sort(key=lambda item: (item[1] / item[0]), reverse=True)
    
    best_val = 0
    node_count = 0
    
    def get_bound(idx, cur_w, cur_v):
        if cur_w > w_cap:
            return 0
        bound = cur_v
        rem_w = w_cap - cur_w
        for i in range(idx, n):
            w, v = items[i]
            if rem_w >= w:
                rem_w -= w
                bound += v
            else:
                bound += v * (rem_w / w)
                break
        return bound

    def dfs(idx, cur_w, cur_v):
        nonlocal best_val, node_count
        node_count += 1
        
        if cur_v > best_val:
            best_val = cur_v
            
        if idx == n:
            return
            
        # Upper bound pruning
        ub = get_bound(idx, cur_w, cur_v)
        if ub <= best_val:
            return
            
        # Branch 1: include items[idx] (if fits)
        w, v = items[idx]
        if cur_w + w <= w_cap:
            dfs(idx + 1, cur_w + w, cur_v + v)
            
        # Branch 2: exclude items[idx]
        # Check bound without items[idx]
        ub_without = get_bound(idx + 1, cur_w, cur_v)
        if ub_without > best_val:
            dfs(idx + 1, cur_w, cur_v)

    dfs(0, 0, 0)
    print(f"{best_val} {node_count}")

if __name__ == '__main__':
    solve()
