import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    a = int(lines[0])
    b = int(lines[1])
    c = int(lines[2])
    L = int(lines[3])
    R = int(lines[4])
    
    # f(x) = a * x^2 + b * x + c, a > 0
    # Find integer x in [L, R] minimizing f(x)
    def f(x):
        return a * x * x + b * x + c
        
    low = L
    high = R
    while high - low >= 3:
        m1 = low + (high - low) // 3
        m2 = high - (high - low) // 3
        if f(m1) <= f(m2):
            high = m2
        else:
            low = m1
            
    best_x = low
    best_val = f(low)
    for x in range(low + 1, high + 1):
        v = f(x)
        if v < best_val:
            best_val = v
            best_x = x
            
    print(best_x)
    print(best_val)

if __name__ == "__main__":
    solve()
