import sys

def in_circle(a, b, c, d):
    # Test if point d lies strictly inside circumcircle of triangle (a, b, c) in CCW order
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    
    # Check CCW
    ccw = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if ccw < 0:
        b, c = c, b
        bx, by, cx, cy = cx, cy, bx, by
        
    ax_d, ay_d = ax - dx, ay - dy
    bx_d, by_d = bx - dx, by - dy
    cx_d, cy_d = cx - dx, cy - dy
    
    det = (
        (ax_d**2 + ay_d**2) * (bx_d * cy_d - by_d * cx_d) -
        (bx_d**2 + by_d**2) * (ax_d * cy_d - ay_d * cx_d) +
        (cx_d**2 + cy_d**2) * (ax_d * by_d - ay_d * bx_d)
    )
    return det > 1e-9

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    points = []
    idx = 1
    for _ in range(n):
        x = float(input_data[idx])
        y = float(input_data[idx+1])
        idx += 2
        points.append((x, y))
        
    if n < 3:
        print(n - 1)
        return
    if n == 3:
        print(3)
        return
        
    # Delaunay triangulation by empty circumcircle check
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                # Check if triangle (i, j, k) is non-degenerate
                p1, p2, p3 = points[i], points[j], points[k]
                cross = (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
                if abs(cross) < 1e-9:
                    continue
                # Check empty circumcircle
                is_delaunay = True
                for m in range(n):
                    if m == i or m == j or m == k:
                        continue
                    if in_circle(p1, p2, p3, points[m]):
                        is_delaunay = False
                        break
                if is_delaunay:
                    edges.add((min(i, j), max(i, j)))
                    edges.add((min(j, k), max(j, k)))
                    edges.add((min(i, k), max(i, k)))
                    
    print(len(edges))

if __name__ == '__main__':
    solve()
