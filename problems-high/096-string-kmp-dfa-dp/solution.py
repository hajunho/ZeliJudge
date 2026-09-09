import sys

MOD = 1000000007

def build_kmp_dfa(p):
    m = len(p)
    # failure function pi
    pi = [0] * m
    j = 0
    for i in range(1, m):
        while j > 0 and p[i] != p[j]:
            j = pi[j - 1]
        if p[i] == p[j]:
            j += 1
            pi[i] = j
            
    # dfa[state][char_idx] -> next_state
    # chars: 'a' -> 0, 'b' -> 1
    dfa = [[0, 0] for _ in range(m + 1)]
    for s in range(m):
        for c_idx, ch in enumerate(('a', 'b')):
            curr = s
            while curr > 0 and p[curr] != ch:
                curr = pi[curr - 1]
            if p[curr] == ch:
                dfa[s][c_idx] = curr + 1
            else:
                dfa[s][c_idx] = 0
    return dfa

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    l = int(input_data[0])
    p = input_data[1]
    m = len(p)
    
    if l < m:
        # Cannot contain P
        print(pow(2, l, MOD))
        return
        
    dfa = build_kmp_dfa(p)
    
    # dp[state]
    dp = [0] * m
    dp[0] = 1
    
    for _ in range(l):
        nxt_dp = [0] * m
        for s in range(m):
            if not dp[s]:
                continue
            val = dp[s]
            for c_idx in (0, 1):
                nxt_s = dfa[s][c_idx]
                if nxt_s < m: # valid state (not reaching pattern match m)
                    nxt_dp[nxt_s] = (nxt_dp[nxt_s] + val) % MOD
        dp = nxt_dp
        
    ans = sum(dp) % MOD
    print(ans)

if __name__ == '__main__':
    main()
