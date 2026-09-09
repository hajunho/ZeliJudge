import sys

def ccw(p1, p2, p3):
    val = (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
    if val > 0:
        return 1
    elif val < 0:
        return -1
    return 0

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    poly = []
    idx = 1
    for _ in range(n):
        poly.append((int(input_data[idx]), int(input_data[idx+1])))
        idx += 2
        
    q = int(input_data[idx])
    idx += 1
    
    p0 = poly[0]
    out = []
    
    for _ in range(q):
        pt = (int(input_data[idx]), int(input_data[idx+1]))
        idx += 2
        
        # 1. 외곽 두 변 검사
        c_first = ccw(p0, poly[1], pt)
        c_last = ccw(p0, poly[-1], pt)
        
        if c_first < 0 or c_last > 0:
            out.append("0")
            continue
            
        if c_first == 0:
            # 선분 p0 - poly[1] 위에 있는지
            if min(p0[0], poly[1][0]) <= pt[0] <= max(p0[0], poly[1][0]) and \
               min(p0[1], poly[1][1]) <= pt[1] <= max(p0[1], poly[1][1]):
                out.append("1")
            else:
                out.append("0")
            continue
            
        if c_last == 0:
            # 선분 p0 - poly[-1] 위에 있는지
            if min(p0[0], poly[-1][0]) <= pt[0] <= max(p0[0], poly[-1][0]) and \
               min(p0[1], poly[-1][1]) <= pt[1] <= max(p0[1], poly[-1][1]):
                out.append("1")
            else:
                out.append("0")
            continue
            
        # 2. 이진 탐색으로 섹터 찾기
        left = 1
        right = n - 1
        sector = 1
        while left <= right:
            mid = (left + right) // 2
            if ccw(p0, poly[mid], pt) >= 0:
                sector = mid
                left = mid + 1
            else:
                right = mid - 1
                
        # 삼각형 p0 - poly[sector] - poly[sector + 1] 내부 검사
        if sector + 1 < n and ccw(poly[sector], poly[sector + 1], pt) >= 0:
            out.append("1")
        else:
            out.append("0")
            
    print("\n".join(out))

if __name__ == "__main__":
    solve()
