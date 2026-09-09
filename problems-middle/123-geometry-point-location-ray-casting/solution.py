import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    poly = []
    idx = 1
    for _ in range(N):
        x = int(lines[idx])
        y = int(lines[idx+1])
        poly.append((x, y))
        idx += 2
        
    M = int(lines[idx])
    idx += 1
    queries = []
    for _ in range(M):
        qx = int(lines[idx])
        qy = int(lines[idx+1])
        queries.append((qx, qy))
        idx += 2
        
    out = []
    for qx, qy in queries:
        on_boundary = False
        inside = False
        
        for i in range(N):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % N]
            
            # Check if point is on segment (x1, y1) - (x2, y2)
            cross = (x2 - x1) * (qy - y1) - (y2 - y1) * (qx - x1)
            if cross == 0:
                if min(x1, x2) <= qx <= max(x1, x2) and min(y1, y2) <= qy <= max(y1, y2):
                    on_boundary = True
                    break
                    
            # Ray casting: ray towards +x (horizontal)
            if (y1 > qy) != (y2 > qy):
                # Compute x-coordinate of intersection
                intersect_x = x1 + (qy - y1) * (x2 - x1) / (y2 - y1)
                if qx < intersect_x:
                    inside = not inside
                    
        if on_boundary:
            out.append("ON")
        elif inside:
            out.append("IN")
        else:
            out.append("OUT")
            
    print('\n'.join(out))

if __name__ == "__main__":
    solve()
