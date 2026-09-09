import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    a = [int(x) for x in input_data[1:1+n]]
    b = [int(x) for x in input_data[1+n:1+2*n]]
    
    # dp[i] = min_{j < i} (dp[j] + a[i] * b[j])
    # lines: (m, k) -> y = m*x + k
    lines_m = []
    lines_k = []
    
    def cross_x(idx1, idx2):
        # intersection of line1 and line2: (k1 - k2) / (m2 - m1)
        return (lines_k[idx1] - lines_k[idx2]) / (lines_m[idx2] - lines_m[idx1])
        
    lines_m.append(b[0])
    lines_k.append(0)
    
    ptr = 0
    cur_dp = 0
    
    for i in range(1, n):
        x = a[i]
        while ptr + 1 < len(lines_m) and lines_m[ptr] * x + lines_k[ptr] >= lines_m[ptr + 1] * x + lines_k[ptr + 1]:
            ptr += 1
            
        cur_dp = lines_m[ptr] * x + lines_k[ptr]
        
        # 새 직선 추가: y = b[i]*x + cur_dp
        new_m = b[i]
        new_k = cur_dp
        
        while len(lines_m) >= 2:
            # cross_x(len-2, len-1) >= cross_x(len-1, new)
            idx1 = len(lines_m) - 2
            idx2 = len(lines_m) - 1
            if cross_x(idx1, idx2) >= (lines_k[idx2] - new_k) / (new_m - lines_m[idx2]):
                lines_m.pop()
                lines_k.pop()
                if ptr >= len(lines_m):
                    ptr = len(lines_m) - 1
            else:
                break
                
        lines_m.append(new_m)
        lines_k.append(new_k)
        
    print(cur_dp)

if __name__ == "__main__":
    solve()
