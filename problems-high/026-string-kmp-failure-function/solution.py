import sys

def get_pi(p):
    m = len(p)
    pi = [0] * m
    j = 0
    for i in range(1, m):
        while j > 0 and p[i] != p[j]:
            j = pi[j - 1]
        if p[i] == p[j]:
            j += 1
            pi[i] = j
    return pi

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    t = lines[0]
    p = lines[1] if len(lines) > 1 else ""
    
    n = len(t)
    m = len(p)
    if m == 0 or n < m:
        print(0)
        return
        
    pi = get_pi(p)
    matches = []
    j = 0
    for i in range(n):
        while j > 0 and t[i] != p[j]:
            j = pi[j - 1]
        if t[i] == p[j]:
            if j == m - 1:
                matches.append(i - m + 2) # 1-based
                j = pi[j]
            else:
                j += 1
                
    print(len(matches))
    if matches:
        print(*(matches))

if __name__ == "__main__":
    solve()
