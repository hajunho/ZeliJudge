import sys

def dist_sq(p1, p2):
    return (p1[0] - p2[0])**2 + (p1[1] - p2[1])**2

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
        
    points.sort(key=lambda p: p[0])
    
    def closest_pair(pts):
        n = len(pts)
        if n <= 3:
            min_d = 10**18
            for i in range(n):
                for j in range(i + 1, n):
                    min_d = min(min_d, dist_sq(pts[i], pts[j]))
            return min_d
            
        mid = n // 2
        mid_x = pts[mid][0]
        
        d_left = closest_pair(pts[:mid])
        d_right = closest_pair(pts[mid:])
        d = min(d_left, d_right)
        
        # Strip within sqrt(d) of mid_x
        # To avoid float sqrt, check (x - mid_x)^2 < d
        strip = [p for p in pts if (p[0] - mid_x)**2 < d]
        strip.sort(key=lambda p: p[1])
        
        m = len(strip)
        for i in range(m):
            # At most 7 points to check
            for j in range(i + 1, m):
                if (strip[j][1] - strip[i][1])**2 >= d:
                    break
                d = min(d, dist_sq(strip[i], strip[j]))
                
        return d
        
    ans = closest_pair(points)
    print(ans)

if __name__ == "__main__":
    solve()
