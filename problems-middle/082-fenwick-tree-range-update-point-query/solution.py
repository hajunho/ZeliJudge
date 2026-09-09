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
    
    # Fenwick Tree on Difference Array
    # diff[i] represents delta
    tree = [0] * (N + 2)
    
    def add(i, val):
        while i <= N:
            tree[i] += val
            i += (i & -i)
            
    def query(i):
        s = 0
        while i > 0:
            s += tree[i]
            i -= (i & -i)
        return s
        
    out = []
    for _ in range(Q):
        cmd = int(lines[idx])
        if cmd == 1:
            # 1 L R v
            L = int(lines[idx+1])
            R = int(lines[idx+2])
            v = int(lines[idx+3])
            add(L, v)
            add(R + 1, -v)
            idx += 4
        else:
            # 2 i
            pos = int(lines[idx+1])
            ans = arr[pos-1] + query(pos)
            out.append(str(ans))
            idx += 2
            
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
