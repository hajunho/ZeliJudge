import sys
import math
from collections import deque

def ccw(p1, p2, p3):
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

def line_intersection(l1, l2):
    # l1: p1, p2 / l2: p3, p4
    x1, y1 = l1[0]
    x2, y2 = l1[1]
    x3, y3 = l2[0]
    x4, y4 = l2[1]
    
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-12:
        return None
    px = ((x1*y2 - y1*x2) * (x3 - x4) - (x1 - x2) * (x3*y4 - y3*x4)) / d
    py = ((x1*y2 - y1*x2) * (y3 - y4) - (y1 - y2) * (x3*y4 - y3*x4)) / d
    return (px, py)

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    lines = []
    idx = 1
    for _ in range(n):
        x1 = float(input_data[idx])
        y1 = float(input_data[idx+1])
        x2 = float(input_data[idx+2])
        y2 = float(input_data[idx+3])
        idx += 4
        ang = math.atan2(y2 - y1, x2 - x1)
        lines.append(((x1, y1), (x2, y2), ang))
        
    # 각도순 정렬 (같은 각도는 더 안쪽의 직선 유지)
    lines.sort(key=lambda x: x[2])
    unique_lines = []
    for l in lines:
        if unique_lines and abs(unique_lines[-1][2] - l[2]) < 1e-9:
            if ccw(unique_lines[-1][0], unique_lines[-1][1], l[0]) < 0:
                unique_lines[-1] = l
        else:
            unique_lines.append(l)
            
    q = deque()
    for l in unique_lines:
        while len(q) >= 2:
            pt = line_intersection(q[-1], q[-2])
            if pt is None or ccw(l[0], l[1], pt) < -1e-9:
                q.pop()
            else:
                break
        while len(q) >= 2:
            pt = line_intersection(q[0], q[1])
            if pt is None or ccw(l[0], l[1], pt) < -1e-9:
                q.popleft()
            else:
                break
        q.append(l)
        
    while len(q) >= 3:
        pt = line_intersection(q[-1], q[-2])
        if pt is None or ccw(q[0][0], q[0][1], pt) < -1e-9:
            q.pop()
        else:
            break
            
    while len(q) >= 3:
        pt = line_intersection(q[0], q[1])
        if pt is None or ccw(q[-1][0], q[-1][1], pt) < -1e-9:
            q.popleft()
        else:
            break
            
    if len(q) < 3:
        print("0.0")
        return
        
    pts = []
    m = len(q)
    for i in range(m):
        pt = line_intersection(q[i], q[(i + 1) % m])
        if pt is None:
            print("0.0")
            return
        pts.append(pt)
        
    area = 0.0
    for i in range(len(pts)):
        nxt = (i + 1) % len(pts)
        area += pts[i][0] * pts[nxt][1] - pts[nxt][0] * pts[i][1]
    area = abs(area) / 2.0
    print(f"{area:.1f}")

if __name__ == "__main__":
    solve()
