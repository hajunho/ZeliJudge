import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    S = lines[0]
    P = lines[1]
    
    n = len(S)
    m = len(P)
    if n < m:
        print(0)
        return
        
    BASE = 31
    MOD = 1000000007
    
    p_hash = 0
    s_hash = 0
    power = 1
    for i in range(m):
        p_hash = (p_hash * BASE + ord(P[i])) % MOD
        s_hash = (s_hash * BASE + ord(S[i])) % MOD
        if i < m - 1:
            power = (power * BASE) % MOD
            
    matches = []
    for i in range(n - m + 1):
        if s_hash == p_hash:
            if S[i:i+m] == P:
                matches.append(i + 1)
        if i + m < n:
            s_hash = ((s_hash - ord(S[i]) * power) * BASE + ord(S[i+m])) % MOD
            s_hash = (s_hash + MOD) % MOD
            
    print(len(matches))
    if matches:
        print(' '.join(map(str, matches)))

if __name__ == "__main__":
    solve()
