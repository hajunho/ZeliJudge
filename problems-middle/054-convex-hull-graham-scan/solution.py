import sys

def ccw(p1, p2, p3):
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    pts = []
    for _ in range(N):
        x = int(lines[idx])
        y = int(lines[idx+1])
        pts.append((x, y))
        idx += 2
        
    pts = sorted(list(set(pts)))
    if len(pts) <= 2:
        print(len(pts))
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
    print(len(hull))

if __name__ == "__main__":
    solve()
