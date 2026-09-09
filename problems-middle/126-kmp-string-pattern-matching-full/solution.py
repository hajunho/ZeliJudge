import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    T = lines[0]
    P = lines[1]
    
    n = len(T)
    m = len(P)
    
    # 1. Failure function pi
    pi = [0] * m
    j = 0
    for i in range(1, m):
        while j > 0 and P[i] != P[j]:
            j = pi[j - 1]
        if P[i] == P[j]:
            j += 1
            pi[i] = j
            
    # 2. KMP Search
    matches = []
    j = 0
    for i in range(n):
        while j > 0 and T[i] != P[j]:
            j = pi[j - 1]
        if T[i] == P[j]:
            if j == m - 1:
                matches.append(i - m + 2) # 1-based start index
                j = pi[j]
            else:
                j += 1
                
    print(len(matches))
    if matches:
        print(' '.join(map(str, matches)))

if __name__ == "__main__":
    solve()
