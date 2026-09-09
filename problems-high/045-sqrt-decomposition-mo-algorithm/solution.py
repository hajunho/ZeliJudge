import sys
import math

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    arr = [int(x) for x in input_data[1:1+n]]
    
    q = int(input_data[1+n])
    queries = []
    idx = 2 + n
    for i in range(q):
        ql = int(input_data[idx]) - 1
        qr = int(input_data[idx+1]) - 1
        idx += 2
        queries.append((ql, qr, i))
        
    block_size = max(1, int(math.sqrt(n)))
    queries.sort(key=lambda x: (x[0] // block_size, x[1] if (x[0] // block_size) % 2 == 0 else -x[1]))
    
    count_map = [0] * 1000001
    distinct_count = 0
    
    def add(val):
        nonlocal distinct_count
        if count_map[val] == 0:
            distinct_count += 1
        count_map[val] += 1
        
    def remove(val):
        nonlocal distinct_count
        count_map[val] -= 1
        if count_map[val] == 0:
            distinct_count -= 1

    cur_l = 0
    cur_r = -1
    ans = [0] * q
    
    for ql, qr, qidx in queries:
        while cur_l > ql:
            cur_l -= 1
            add(arr[cur_l])
        while cur_r < qr:
            cur_r += 1
            add(arr[cur_r])
        while cur_l < ql:
            remove(arr[cur_l])
            cur_l += 1
        while cur_r > qr:
            remove(arr[cur_r])
            cur_r -= 1
        ans[qidx] = distinct_count
        
    out = [str(x) for x in ans]
    print("\n".join(out))

if __name__ == "__main__":
    solve()
