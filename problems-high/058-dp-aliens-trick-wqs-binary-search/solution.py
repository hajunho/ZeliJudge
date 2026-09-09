import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k_target = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    # g(C): dp with penalty C per segment
    # dp[i][0]: i번째 원소 미선택
    # dp[i][1]: i번째 원소 선택 중
    def check(c):
        dp0_val, dp0_cnt = 0, 0
        dp1_val, dp1_cnt = -10**18, 0
        
        for x in arr:
            # 1. dp1 전이: 기존 구간 연장 vs 새 구간 시작(패널티 c 부과)
            extend_val = dp1_val + x
            extend_cnt = dp1_cnt
            
            new_val = dp0_val + x - c
            new_cnt = dp0_cnt + 1
            
            if new_val > extend_val or (new_val == extend_val and new_cnt < extend_cnt):
                next_dp1_val, next_dp1_cnt = new_val, new_cnt
            else:
                next_dp1_val, next_dp1_cnt = extend_val, extend_cnt
                
            # 2. dp0 전이: dp0 유지 vs dp1 종료
            if next_dp1_val > dp0_val or (next_dp1_val == dp0_val and next_dp1_cnt < dp0_cnt):
                next_dp0_val, next_dp0_cnt = next_dp1_val, next_dp1_cnt
            else:
                next_dp0_val, next_dp0_cnt = dp0_val, dp0_cnt
                
            dp0_val, dp0_cnt = next_dp0_val, next_dp0_cnt
            dp1_val, dp1_cnt = next_dp1_val, next_dp1_cnt
            
        return dp0_val, dp0_cnt

    low = -2000000000
    high = 2000000000
    best_c = 0
    
    while low <= high:
        mid = (low + high) // 2
        val, cnt = check(mid)
        if cnt >= k_target:
            best_c = mid
            low = mid + 1
        else:
            high = mid - 1
            
    val, cnt = check(best_c)
    ans = val + k_target * best_c
    print(ans)

if __name__ == "__main__":
    solve()
