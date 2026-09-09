import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    
    ans = N
    d = 2
    temp = N
    while d * d <= temp:
        if temp % d == 0:
            while temp % d == 0:
                temp //= d
            ans -= ans // d
        d += 1
    if temp > 1:
        ans -= ans // temp
        
    print(ans)

if __name__ == "__main__":
    solve()
