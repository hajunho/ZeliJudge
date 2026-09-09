import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    tree = [0] * (n + 1)
    
    def add(idx, val):
        while idx <= n:
            tree[idx] += val
            idx += idx & -idx
            
    def prefix_sum(idx):
        s = 0
        while idx > 0:
            s += tree[idx]
            idx -= idx & -idx
        return s
        
    for i in range(1, n + 1):
        add(i, arr[i - 1])
        
    ptr = 2 + n
    out = []
    for _ in range(q):
        qtype = int(input_data[ptr])
        a = int(input_data[ptr+1])
        b = int(input_data[ptr+2])
        ptr += 3
        if qtype == 1:
            add(a, b)
        else:
            ans = prefix_sum(b) - prefix_sum(a - 1)
            out.append(str(ans))
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
