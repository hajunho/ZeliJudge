import sys
import math

def ccw(p1, p2, p3):
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

def dot(p1, p2, p3):
    return (p2[0] - p1[0]) * (p3[0] - p1[0]) + (p2[1] - p1[1]) * (p3[1] - p1[1])

def dist_sq(p1, p2):
    return (p1[0] - p2[0])**2 + (p1[1] - p2[1])**2

def convex_hull(pts):
    pts = sorted(set(pts))
    if len(pts) <= 2:
        return pts
        
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
        
    return lower[:-1] + upper[:-1]

def min_bounding_box(pts):
    hull = convex_hull(pts)
    n = len(hull)
    if n <= 2:
        return 0.0
        
    top = 1
    right = 1
    left = 1
    min_area = float('inf')
    
    for i in range(n):
        p1 = hull[i]
        p2 = hull[(i + 1) % n]
        edge_len = math.sqrt(dist_sq(p1, p2))
        if edge_len == 0:
            continue
            
        while ccw(p1, p2, hull[(top + 1) % n]) > ccw(p1, p2, hull[top]):
            top = (top + 1) % n
            
        while dot(p1, p2, hull[(right + 1) % n]) > dot(p1, p2, hull[right]):
            right = (right + 1) % n
            
        if i == 0:
            left = top
            
        while dot(p1, p2, hull[(left + 1) % n]) < dot(p1, p2, hull[left]):
            left = (left + 1) % n
            
        height = abs(ccw(p1, p2, hull[top])) / edge_len
        width = (dot(p1, p2, hull[right]) - dot(p1, p2, hull[left])) / edge_len
        area = width * height
        if area < min_area:
            min_area = area
            
    return min_area

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    pts = []
    idx = 1
    for _ in range(n):
        x = int(input_data[idx])
        y = int(input_data[idx + 1])
        pts.append((x, y))
        idx += 2
        
    ans = min_bounding_box(pts)
    print(f"{ans:.2f}")

if __name__ == '__main__':
    main()
