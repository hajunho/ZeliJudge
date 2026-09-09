import sys

def ccw(x1, y1, x2, y2, x3, y3):
    return (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    poly = []
    for _ in range(N):
        x = int(lines[idx])
        y = int(lines[idx+1])
        poly.append((x, y))
        idx += 2
    px = int(lines[idx])
    py = int(lines[idx+1])
    
    inside = True
    for i in range(N):
        p1 = poly[i]
        p2 = poly[(i + 1) % N]
        if ccw(p1[0], p1[1], p2[0], p2[1], px, py) < 0:
            inside = False
            break
    print(1 if inside else 0)

if __name__ == "__main__":
    solve()
