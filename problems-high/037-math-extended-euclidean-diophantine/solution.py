import sys

def ext_gcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x1, y1 = ext_gcd(b, a % b)
    x = y1
    y = x1 - (a // b) * y1
    return g, x, y

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    a = int(input_data[0])
    b = int(input_data[1])
    c = int(input_data[2])
    
    g, x0, y0 = ext_gcd(a, b)
    
    if c % g != 0:
        print(-1)
        return
        
    k = c // g
    x = x0 * k
    y = y0 * k
    
    step_x = b // g
    step_y = a // g
    
    x = x % step_x
    if x < 0:
        x += step_x
    y = (c - a * x) // b
    
    print(f"{x} {y}")

if __name__ == "__main__":
    solve()
