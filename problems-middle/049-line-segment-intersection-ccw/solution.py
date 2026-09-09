import sys

def ccw(x1, y1, x2, y2, x3, y3):
    cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
    if cross > 0:
        return 1
    elif cross < 0:
        return -1
    else:
        return 0

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    x1, y1, x2, y2 = int(lines[0]), int(lines[1]), int(lines[2]), int(lines[3])
    x3, y3, x4, y4 = int(lines[4]), int(lines[5]), int(lines[6]), int(lines[7])
    
    ccw1 = ccw(x1, y1, x2, y2, x3, y3) * ccw(x1, y1, x2, y2, x4, y4)
    ccw2 = ccw(x3, y3, x4, y4, x1, y1) * ccw(x3, y3, x4, y4, x2, y2)
    
    if ccw1 <= 0 and ccw2 <= 0:
        if ccw1 == 0 and ccw2 == 0:
            # Collinear: check 1D bounding box overlap
            if (min(x1, x2) <= max(x3, x4) and min(x3, x4) <= max(x1, x2) and
                min(y1, y2) <= max(y3, y4) and min(y3, y4) <= max(y1, y2)):
                print(1)
            else:
                print(0)
        else:
            print(1)
    else:
        print(0)

if __name__ == "__main__":
    solve()
