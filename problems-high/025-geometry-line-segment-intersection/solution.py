import sys

def ccw(p1, p2, p3):
    val = (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
    if val > 0:
        return 1
    elif val < 0:
        return -1
    return 0

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    x1, y1, x2, y2 = map(int, lines[0:4])
    x3, y3, x4, y4 = map(int, lines[4:8])
    
    p1 = (x1, y1)
    p2 = (x2, y2)
    p3 = (x3, y3)
    p4 = (x4, y4)
    
    c1 = ccw(p1, p2, p3) * ccw(p1, p2, p4)
    c2 = ccw(p3, p4, p1) * ccw(p3, p4, p2)
    
    if c1 <= 0 and c2 <= 0:
        if c1 == 0 and c2 == 0:
            if min(p1[0], p2[0]) <= max(p3[0], p4[0]) and min(p3[0], p4[0]) <= max(p1[0], p2[0]) and \
               min(p1[1], p2[1]) <= max(p3[1], p4[1]) and min(p3[1], p4[1]) <= max(p1[1], p2[1]):
                print(1)
            else:
                print(0)
        else:
            print(1)
    else:
        print(0)

if __name__ == "__main__":
    solve()
