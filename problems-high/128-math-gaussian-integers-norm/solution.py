import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    # Factorize n
    temp = n
    ans = 4
    
    # Factor out 2
    while temp % 2 == 0:
        temp //= 2
        
    d = 3
    while d * d <= temp:
        if temp % d == 0:
            cnt = 0
            while temp % d == 0:
                cnt += 1
                temp //= d
            if d % 4 == 1:
                ans *= (cnt + 1)
            elif d % 4 == 3:
                if cnt % 2 != 0:
                    print(0)
                    return
        d += 2
        
    if temp > 1:
        if temp % 4 == 1:
            ans *= (1 + 1)
        elif temp % 4 == 3:
            print(0)
            return
            
    print(ans)

if __name__ == '__main__':
    solve()
