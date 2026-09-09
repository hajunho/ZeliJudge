import sys

def ccw(p1, p2, p3):
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

def dist_sq(p1, p2):
    return (p1[0] - p2[0])**2 + (p1[1] - p2[1])**2

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    points = []
    idx = 1
    for _ in range(n):
        x = int(input_data[idx])
        y = int(input_data[idx+1])
        idx += 2
        points.append((x, y))
        
    points.sort()
    
    # 볼록 껍질
    lower = []
    for p in points:
        while len(lower) >= 2 and ccw(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
        
    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and ccw(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
        
    hull = lower[:-1] + upper[:-1]
    h = len(hull)
    if h == 2:
        print(dist_sq(hull[0], hull[1]))
        return
        
    max_d = 0
    j = 1
    for i in range(h):
        ni = (i + 1) % h
        while True:
            nj = (j + 1) % h
            # 외적으로 높이(넓이) 비교
            vec_edge = (hull[ni][0] - hull[i][0], hull[ni][1] - hull[i][1])
            area1 = abs(ccw(hull[i], hull[ni], hull[j]))
            area2 = abs(ccw(hull[i], hull[ni], hull[nj]))
            if area2 > area1:
                j = nj
            else:
                break
        max_d = max(max_d, dist_sq(hull[i], hull[j]), dist_sq(hull[ni], hull[j]))
        
    print(max_d)

if __name__ == "__main__":
    solve()
