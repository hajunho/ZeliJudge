import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    S = lines[0]
    
    # Transform: insert '#' between characters and at ends
    # e.g., 'aba' -> '#a#b#a#'
    T = '#' + '#'.join(S) + '#'
    M = len(T)
    
    P = [0] * M
    C = 0
    R = 0
    
    for i in range(M):
        mirror = 2 * C - i
        if i < R:
            P[i] = min(R - i, P[mirror])
        else:
            P[i] = 0
            
        # Expand around i
        while i - 1 - P[i] >= 0 and i + 1 + P[i] < M and T[i - 1 - P[i]] == T[i + 1 + P[i]]:
            P[i] += 1
            
        if i + P[i] > R:
            C = i
            R = i + P[i]
            
    max_len = max(P)
    print(max_len)

if __name__ == "__main__":
    solve()
