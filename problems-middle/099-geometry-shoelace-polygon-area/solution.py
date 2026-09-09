import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    points = []
    idx = 1
    for _ in range(N):
        x = int(lines[idx])
        y = int(lines[idx+1])
        points.append((x, y))
        idx += 2
        
    # Shoelace Formula
    # Area = 0.5 * abs(sum(x_i * y_{i+1} - x_{i+1} * y_i))
    total = 0
    for i in range(N):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % N]
        total += x1 * y2 - x2 * y1
        
    area = abs(total) / 2.0
    print(f"{area:.1f}")

if __name__ == "__main__":
    solve()
