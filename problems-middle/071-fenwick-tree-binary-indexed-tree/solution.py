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
    
    # 1-indexed Fenwick Tree
    tree = [0] * (N + 1)
    
    def update(i, delta):
        while i <= N:
            tree[i] += delta
            i += (i & -i)
            
    def query(i):
        s = 0
        while i > 0:
            s += tree[i]
            i -= (i & -i)
        return s
        
    for i in range(1, N + 1):
        update(i, arr[i-1])
        
    out = []
    for _ in range(Q):
        cmd = int(lines[idx])
        if cmd == 1:
            # update: idx, new_val
            pos = int(lines[idx+1])
            new_val = int(lines[idx+2])
            delta = new_val - arr[pos-1]
            arr[pos-1] = new_val
            update(pos, delta)
            idx += 3
        else:
            # sum query: L, R
            L = int(lines[idx+1])
            R = int(lines[idx+2])
            ans = query(R) - query(L - 1)
            out.append(str(ans))
            idx += 3
            
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
