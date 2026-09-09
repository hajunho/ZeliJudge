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
        
    def ccw(p1, p2, p3):
        return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
        
    def dist_sq(p1, p2):
        return (p1[0] - p2[0])**2 + (p1[1] - p2[1])**2
        
    # Step 1: Convex Hull via Monotone Chain
    pts = sorted(set(points))
    if len(pts) <= 2:
        if len(pts) == 1:
            print(0)
        else:
            print(dist_sq(pts[0], pts[1]))
        return
        
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
    H = len(hull)
    
    if H <= 2:
        print(dist_sq(hull[0], hull[1]))
        return
        
    # Step 2: Rotating Calipers
    # Find antipodal pairs
    max_d = 0
    j = 1
    for i in range(H):
        ni = (i + 1) % H
        # Vector ni - i
        while True:
            nj = (j + 1) % H
            # Cross product area comparison
            # Triangle (hull[i], hull[ni], hull[nj]) vs (hull[i], hull[ni], hull[j])
            area1 = abs(ccw(hull[i], hull[ni], hull[j]))
            area2 = abs(ccw(hull[i], hull[ni], hull[nj]))
            if area2 > area1:
                j = nj
            else:
                break
        max_d = max(max_d, dist_sq(hull[i], hull[j]))
        max_d = max(max_d, dist_sq(hull[ni], hull[j]))
        
    print(max_d)

if __name__ == "__main__":
    solve()
