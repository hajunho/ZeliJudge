import sys

def solve():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    t = "#" + "#".join(s) + "#"
    n = len(t)
    p = [0] * n
    
    c = 0
    r = 0
    max_len = 0
    
    for i in range(n):
        if i < r:
            p[i] = min(r - i, p[2 * c - i])
        else:
            p[i] = 0
            
        while i - p[i] - 1 >= 0 and i + p[i] + 1 < n and t[i - p[i] - 1] == t[i + p[i] + 1]:
            p[i] += 1
            
        if i + p[i] > r:
            c = i
            r = i + p[i]
            
        if p[i] > max_len:
            max_len = p[i]
            
    print(max_len)

if __name__ == "__main__":
    solve()
