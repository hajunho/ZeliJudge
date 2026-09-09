import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    events = []
    y_set = set()
    idx = 1
    for _ in range(n):
        x1 = int(input_data[idx])
        y1 = int(input_data[idx+1])
        x2 = int(input_data[idx+2])
        y2 = int(input_data[idx+3])
        idx += 4
        
        events.append((x1, 1, y1, y2))
        events.append((x2, -1, y1, y2))
        y_set.add(y1)
        y_set.add(y2)
        
    events.sort(key=lambda x: x[0])
    sorted_y = sorted(list(y_set))
    y_to_idx = {val: i for i, val in enumerate(sorted_y)}
    
    num_y = len(sorted_y)
    cnt = [0] * (4 * num_y)
    tree_len = [0] * (4 * num_y)
    
    def update(node, start, end, ql, qr, val):
        if qr <= start or end <= ql:
            return
        if ql <= start and end <= qr:
            cnt[node] += val
        else:
            mid = (start + end) // 2
            update(node * 2, start, mid, ql, qr, val)
            update(node * 2 + 1, mid + 1, end, ql, qr, val)
            
        if cnt[node] > 0:
            tree_len[node] = sorted_y[end] - sorted_y[start]
        else:
            if start + 1 == end:
                tree_len[node] = 0
            else:
                tree_len[node] = tree_len[node * 2] + tree_len[node * 2 + 1]

    total_area = 0
    prev_x = events[0][0]
    
    for x, event_type, y1, y2 in events:
        dx = x - prev_x
        total_area += dx * tree_len[1]
        prev_x = x
        update(1, 0, num_y - 1, y_to_idx[y1], y_to_idx[y2], event_type)
        
    print(total_area)

if __name__ == "__main__":
    solve()
