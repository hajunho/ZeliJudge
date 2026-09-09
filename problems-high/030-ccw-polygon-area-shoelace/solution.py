import sys

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
        
    s1 = 0
    s2 = 0
    for i in range(n):
        nxt = (i + 1) % n
        s1 += points[i][0] * points[nxt][1]
        s2 += points[nxt][0] * points[i][1]
        
    area = abs(s1 - s2) / 2.0
    print(f"{area:.1f}")

if __name__ == "__main__":
    solve()
