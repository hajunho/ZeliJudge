import sys

def ext_gcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x1, y1 = ext_gcd(b, a % b)
    x = y1
    y = x1 - (a // b) * y1
    return g, x, y

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    A = int(lines[0])
    B = int(lines[1])
    C = int(lines[2])
    
    # Ax + By = C
    # Condition: C must be divisible by gcd(A, B)
    g, x0, y0 = ext_gcd(A, B)
    
    if C % g != 0:
        print("NO SOLUTION")
        return
        
    scale = C // g
    x_base = x0 * scale
    y_base = y0 * scale
    
    # General solution:
    # x = x_base + k * (B // g)
    # y = y_base - k * (A // g)
    # Find minimal non-negative x (x >= 0)
    step_x = B // g
    step_y = A // g
    
    k = - (x_base // step_x)
    x = x_base + k * step_x
    if x < 0:
        x += step_x
        k += 1
        
    y = y_base - k * step_y
    print(f"{x} {y}")

if __name__ == "__main__":
    solve()
