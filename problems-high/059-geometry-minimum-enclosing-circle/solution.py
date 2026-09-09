import sys
import math
import random

def dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def circle_from_2(p1, p2):
    cx = (p1[0] + p2[0]) / 2.0
    cy = (p1[1] + p2[1]) / 2.0
    r = dist(p1, p2) / 2.0
    return cx, cy, r

def circle_from_3(p1, p2, p3):
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return 0, 0, 0
    ux = ((ax*ax + ay*ay)*(by - cy) + (bx*bx + by*by)*(cy - ay) + (cx*cx + cy*cy)*(ay - by)) / d
    uy = ((ax*ax + ay*ay)*(cx - bx) + (bx*bx + by*by)*(ax - cx) + (cx*cx + cy*cy)*(bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    return ux, uy, r

def is_inside(cx, cy, r, pt):
    return dist((cx, cy), pt) <= r + 1e-9

def solve():
    random.seed(42)
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    points = []
    idx = 1
    for _ in range(n):
        points.append((float(input_data[idx]), float(input_data[idx+1])))
        idx += 2
        
    random.shuffle(points)
    
    cx, cy, r = points[0][0], points[0][1], 0.0
    
    for i in range(1, n):
        if not is_inside(cx, cy, r, points[i]):
            cx, cy, r = points[i][0], points[i][1], 0.0
            for j in range(i):
                if not is_inside(cx, cy, r, points[j]):
                    cx, cy, r = circle_from_2(points[i], points[j])
                    for k in range(j):
                        if not is_inside(cx, cy, r, points[k]):
                            cx, cy, r = circle_from_3(points[i], points[j], points[k])
                            
    print(f"{cx:.2f} {cy:.2f} {r:.2f}")

if __name__ == "__main__":
    solve()
