import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    x_coords = [float(x) for x in input_data[1:1+n]]
    
    def f(pos):
        res = 0.0
        for xi in x_coords:
            d = abs(pos - xi)
            res += d * d * d
        return res

    low = min(x_coords)
    high = max(x_coords)
    
    for _ in range(100):
        m1 = low + (high - low) / 3.0
        m2 = high - (high - low) / 3.0
        if f(m1) < f(m2):
            high = m2
        else:
            low = m1
            
    min_val = f((low + high) / 2.0)
    print(f"{min_val:.2f}")

if __name__ == '__main__':
    solve()
