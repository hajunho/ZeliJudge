import sys
import math

def ext_gcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x1, y1 = ext_gcd(b, a % b)
    x = y1
    y = x1 - (a // b) * y1
    return g, x, y

def count_solutions():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    a = int(input_data[0])
    b = int(input_data[1])
    c = int(input_data[2])
    x1 = int(input_data[3])
    x2 = int(input_data[4])
    y1 = int(input_data[5])
    y2 = int(input_data[6])
    
    g, x0, y0 = ext_gcd(abs(a), abs(b))
    
    if c % g != 0:
        print(0)
        return
        
    x0 *= (c // g)
    y0 *= (c // g)
    
    if a < 0:
        x0 = -x0
    if b < 0:
        y0 = -y0
        
    step_x = b // g
    step_y = -(a // g)
    
    k_min = float('-inf')
    k_max = float('inf')
    
    if step_x > 0:
        k_min = max(k_min, math.ceil((x1 - x0) / step_x))
        k_max = min(k_max, math.floor((x2 - x0) / step_x))
    else:
        k_min = max(k_min, math.ceil((x2 - x0) / step_x))
        k_max = min(k_max, math.floor((x1 - x0) / step_x))
        
    if step_y > 0:
        k_min = max(k_min, math.ceil((y1 - y0) / step_y))
        k_max = min(k_max, math.floor((y2 - y0) / step_y))
    else:
        k_min = max(k_min, math.ceil((y2 - y0) / step_y))
        k_max = min(k_max, math.floor((y1 - y0) / step_y))
        
    if k_min <= k_max:
        print(k_max - k_min + 1)
    else:
        print(0)

if __name__ == '__main__':
    count_solutions()
