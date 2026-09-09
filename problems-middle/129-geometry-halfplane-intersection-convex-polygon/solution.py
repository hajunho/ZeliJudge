import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    # Clip a bounding box [-1000, 1000] x [-1000, 1000] with N half-planes
    # Each halfplane given by directed line (x1, y1) -> (x2, y2), keeping left side: ccw(p1, p2, p) >= 0
    N = int(lines[0])
    idx = 1
    
    # Initial polygon: large bounding square
    poly = [(-1000.0, -1000.0), (1000.0, -1000.0), (1000.0, 1000.0), (-1000.0, 1000.0)]
    
    def ccw(x1, y1, x2, y2, px, py):
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        
    def line_intersection(x1, y1, x2, y2, x3, y3, x4, y4):
        # Line 1: (x1, y1)-(x2, y2), Line 2: (x3, y3)-(x4, y4)
        a1 = y2 - y1
        b1 = x1 - x2
        c1 = a1 * x1 + b1 * y1
        
        a2 = y4 - y3
        b2 = x3 - x4
        c2 = a2 * x3 + b2 * y3
        
        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-9:
            return x3, y3
        x = (b2 * c1 - b1 * c2) / det
        y = (a1 * c2 - a2 * c1) / det
        return x, y
        
    for _ in range(N):
        x1 = float(lines[idx])
        y1 = float(lines[idx+1])
        x2 = float(lines[idx+2])
        y2 = float(lines[idx+3])
        idx += 4
        
        # Sutherland-Hodgman Polygon Clipping
        new_poly = []
        M = len(poly)
        if M == 0:
            continue
        for i in range(M):
            cur = poly[i]
            nxt = poly[(i + 1) % M]
            
            c_cur = ccw(x1, y1, x2, y2, cur[0], cur[1])
            c_nxt = ccw(x1, y1, x2, y2, nxt[0], nxt[1])
            
            if c_cur >= -1e-9: # cur is on left side
                new_poly.append(cur)
                if c_nxt < -1e-9: # nxt is on right side -> add intersection
                    ix, iy = line_intersection(x1, y1, x2, y2, cur[0], cur[1], nxt[0], nxt[1])
                    new_poly.append((ix, iy))
            else: # cur is on right side
                if c_nxt >= -1e-9: # nxt is on left side -> add intersection
                    ix, iy = line_intersection(x1, y1, x2, y2, cur[0], cur[1], nxt[0], nxt[1])
                    new_poly.append((ix, iy))
        poly = new_poly
        
    # Calculate area of clipped polygon
    M = len(poly)
    if M < 3:
        print("0.0")
        return
        
    area = 0.0
    for i in range(M):
        p1 = poly[i]
        p2 = poly[(i + 1) % M]
        area += p1[0] * p2[1] - p2[0] * p1[1]
        
    area = abs(area) / 2.0
    print(f"{area:.1f}")

if __name__ == "__main__":
    solve()
