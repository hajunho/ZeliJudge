import sys
import math
from collections import deque

class Line:
    def __init__(self, p1, p2):
        self.p1 = p1
        self.p2 = p2
        self.v = (p2[0] - p1[0], p2[1] - p1[1])
        self.angle = math.atan2(self.v[1], self.v[0])

def ccw(p1, p2, p3):
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

def line_intersection(l1, l2):
    # p1 + t * v1
    x1, y1 = l1.p1
    dx1, dy1 = l1.v
    x2, y2 = l2.p1
    dx2, dy2 = l2.v
    denom = dx1 * dy2 - dy1 * dx2
    if abs(denom) < 1e-11:
        return None
    t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / denom
    return (x1 + t * dx1, y1 + t * dy1)

def on_left(line, pt):
    return ccw(line.p1, line.p2, pt) > -1e-9

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
        lines.append(Line((x1, y1), (x2, y2)))
        
    lines.sort(key=lambda l: l.angle)
    
    # Remove parallel lines keeping the innermost (leftmost)
    unique_lines = []
    for l in lines:
        if unique_lines and abs(unique_lines[-1].angle - l.angle) < 1e-9:
            if on_left(unique_lines[-1], l.p1):
                continue
            else:
                unique_lines.pop()
        unique_lines.append(l)
        
    dq = deque()
    for l in unique_lines:
        while len(dq) >= 2:
            inter = line_intersection(dq[-2], dq[-1])
            if inter is not None and not on_left(l, inter):
                dq.pop()
            else:
                break
        while len(dq) >= 2:
            inter = line_intersection(dq[0], dq[1])
            if inter is not None and not on_left(l, inter):
                dq.popleft()
            else:
                break
        dq.append(l)
        
    while len(dq) >= 3:
        inter = line_intersection(dq[-2], dq[-1])
        if inter is not None and not on_left(dq[0], inter):
            dq.pop()
        else:
            break
            
    while len(dq) >= 3:
        inter = line_intersection(dq[0], dq[1])
        if inter is not None and not on_left(dq[-1], inter):
            dq.popleft()
        else:
            break
            
    if len(dq) < 3:
        print("0.00")
        return
        
    poly = []
    for i in range(len(dq)):
        nxt = (i + 1) % len(dq)
        inter = line_intersection(dq[i], dq[nxt])
        if inter is None:
            print("0.00")
            return
        poly.append(inter)
        
    # Shoelace formula
    area = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - y1 * x2
    area = abs(area) / 2.0
    print(f"{area:.2f}")

if __name__ == '__main__':
    solve()
