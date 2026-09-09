import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    x1, y1 = int(lines[0]), int(lines[1])
    x2, y2 = int(lines[2]), int(lines[3])
    x3, y3 = int(lines[4]), int(lines[5])
    
    cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
    if cross > 0:
        print(1)
    elif cross < 0:
        print(-1)
    else:
        print(0)

if __name__ == "__main__":
    solve()
