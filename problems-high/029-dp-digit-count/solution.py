import sys

def count_digit(n_str, target):
    if not n_str or int(n_str) < 0:
        return 0
    memo = {}
    
    def dp(idx, is_less, is_started, cur_cnt):
        if idx == len(n_str):
            return cur_cnt if is_started else 0
            
        state = (idx, is_less, is_started, cur_cnt)
        if state in memo:
            return memo[state]
            
        limit = int(n_str[idx]) if not is_less else 9
        res = 0
        
        for d in range(limit + 1):
            next_less = is_less or (d < limit)
            next_started = is_started or (d > 0)
            
            add = 0
            if next_started and d == target:
                add = 1
                
            res += dp(idx + 1, next_less, next_started, cur_cnt + add)
            
        memo[state] = res
        return res

    return dp(0, False, False, 0)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    a = int(input_data[0])
    b = int(input_data[1])
    d = int(input_data[2])
    
    ans_b = count_digit(str(b), d)
    ans_a = count_digit(str(a - 1), d)
    print(ans_b - ans_a)

if __name__ == "__main__":
    solve()
