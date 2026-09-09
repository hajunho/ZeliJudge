import sys
import bisect

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    arr = [int(x) for x in lines[1:1+N]]
    
    # tails[i]: smallest tail of all increasing subsequences of length i+1
    tails = []
    # pos[i]: index in tails where arr[i] was placed
    pos = [0] * N
    
    for i, x in enumerate(arr):
        idx = bisect.bisect_left(tails, x)
        if idx == len(tails):
            tails.append(x)
        else:
            tails[idx] = x
        pos[i] = idx
        
    lis_len = len(tails)
    print(lis_len)
    
    # Reconstruct actual LIS sequence
    curr = lis_len - 1
    seq = []
    for i in range(N - 1, -1, -1):
        if pos[i] == curr:
            seq.append(arr[i])
            curr -= 1
            if curr < 0:
                break
    seq.reverse()
    print(' '.join(map(str, seq)))

if __name__ == "__main__":
    solve()
