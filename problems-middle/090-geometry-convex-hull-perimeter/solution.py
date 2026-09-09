import sys
import math

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
        
    pts = sorted(set(points))
    if len(pts) <= 1:
        print("0.00")
        return
    if len(pts) == 2:
        d = math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
        # Perimeter back and forth: 2 * d
        print(f"{2 * d:.2f}")
        return
        
    def ccw(p1, p2, p3):
        return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
        
    lower = []
    for p in pts:
        while len(lower) >= 2 and ccw(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
        
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and ccw(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
        
    hull = lower[:-1] + upper[:-1]
    
    perimeter = 0.0
    H = len(hull)
    for i in range(H):
        p1 = hull[i]
        p2 = hull[(i + 1) % H]
        perimeter += math.hypot(p1[0] - p2[0], p1[1] - p2[1])
        
    print(f"{perimeter:.2f}")

if __name__ == "__main__":
    solve()
