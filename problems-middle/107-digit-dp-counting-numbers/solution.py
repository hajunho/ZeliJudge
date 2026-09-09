import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N_str = lines[0]
    D = int(lines[1])
    
    L = len(N_str)
    # memo[pos][has_digit][is_less]
    memo = {}
    
    def count(pos, has_digit, is_less):
        if pos == L:
            return 1 if has_digit else 0
        state = (pos, has_digit, is_less)
        if state in memo:
            return memo[state]
            
        limit = 9 if is_less else int(N_str[pos])
        res = 0
        for digit in range(limit + 1):
            next_less = is_less or (digit < limit)
            next_has = has_digit or (digit == D)
            res += count(pos + 1, next_has, next_less)
            
        memo[state] = res
        return res
        
    ans = count(0, False, False)
    print(ans)

if __name__ == "__main__":
    solve()
