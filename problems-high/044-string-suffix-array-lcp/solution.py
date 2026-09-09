import sys

def solve():
    s = sys.stdin.read().strip()
    if not s:
        return
    n = len(s)
    
    # 1. Manber-Myers Suffix Array
    sa = list(range(n))
    rank = [ord(c) for c in s]
    temp_rank = [0] * n
    
    k = 1
    while k < n:
        sa.sort(key=lambda x: (rank[x], rank[x + k] if x + k < n else -1))
        
        temp_rank[sa[0]] = 0
        for i in range(1, n):
            prev = sa[i - 1]
            cur = sa[i]
            prev_pair = (rank[prev], rank[prev + k] if prev + k < n else -1)
            cur_pair = (rank[cur], rank[cur + k] if cur + k < n else -1)
            temp_rank[cur] = temp_rank[prev] + (1 if cur_pair != prev_pair else 0)
            
        rank = temp_rank[:]
        if rank[sa[-1]] == n - 1:
            break
        k *= 2
        
    # 2. Kasai's LCP Algorithm
    pos = [0] * n
    for i in range(n):
        pos[sa[i]] = i
        
    lcp = [0] * n
    h = 0
    for i in range(n):
        if pos[i] > 0:
            j = sa[pos[i] - 1]
            while i + h < n and j + h < n and s[i + h] == s[j + h]:
                h += 1
            lcp[pos[i]] = h
            if h > 0:
                h -= 1
                
    # 1-based index 출력
    sa_out = [str(x + 1) for x in sa]
    lcp_out = ["x"] + [str(x) for x in lcp[1:]]
    
    print(" ".join(sa_out))
    print(" ".join(lcp_out))

if __name__ == "__main__":
    solve()
