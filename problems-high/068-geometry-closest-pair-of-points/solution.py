import sys

def dist_sq(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return dx * dx + dy * dy

def closest_pair(pts):
    # pts sorted by x
    n = len(pts)
    if n <= 3:
        ans = float('inf')
        for i in range(n):
            for j in range(i + 1, n):
                ans = min(ans, dist_sq(pts[i], pts[j]))
        return ans

    mid = n // 2
    mid_x = pts[mid][0]
    
    d = min(closest_pair(pts[:mid]), closest_pair(pts[mid:]))
    
    # Strip points
    strip = []
    for p in pts:
        if (p[0] - mid_x) ** 2 < d:
            strip.append(p)
            
    strip.sort(key=lambda p: p[1])
    
    m = len(strip)
    for i in range(m):
        for j in range(i + 1, m):
            if (strip[j][1] - strip[i][1]) ** 2 >= d:
                break
            d = min(d, dist_sq(strip[i], strip[j]))
            
    return d

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
        
    pts.sort(key=lambda p: (p[0], p[1]))
    # check for duplicate points
    for i in range(n - 1):
        if pts[i] == pts[i + 1]:
            print(0)
            return
            
    ans = closest_pair(pts)
    print(ans)

if __name__ == '__main__':
    main()
