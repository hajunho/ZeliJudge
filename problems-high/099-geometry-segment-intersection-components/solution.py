import sys

def ccw(p1, p2, p3):
    val = (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
    if val > 0:
        return 1
    elif val < 0:
        return -1
    return 0

def intersect(seg1, seg2):
    p1, p2 = (seg1[0], seg1[1]), (seg1[2], seg1[3])
    p3, p4 = (seg2[0], seg2[1]), (seg2[2], seg2[3])
    
    c1 = ccw(p1, p2, p3) * ccw(p1, p2, p4)
    c2 = ccw(p3, p4, p1) * ccw(p3, p4, p2)
    
    if c1 <= 0 and c2 <= 0:
        if ccw(p1, p2, p3) == 0 and ccw(p1, p2, p4) == 0 and ccw(p3, p4, p1) == 0 and ccw(p3, p4, p2) == 0:
            if min(p1[0], p2[0]) <= max(p3[0], p4[0]) and min(p3[0], p4[0]) <= max(p1[0], p2[0]) and                min(p1[1], p2[1]) <= max(p3[1], p4[1]) and min(p3[1], p4[1]) <= max(p1[1], p2[1]):
                return True
            return False
        return True
    return False

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    segs = []
    idx = 1
    for _ in range(n):
        x1 = int(input_data[idx])
        y1 = int(input_data[idx + 1])
        x2 = int(input_data[idx + 2])
        y2 = int(input_data[idx + 3])
        segs.append((x1, y1, x2, y2))
        idx += 4
        
    parent = list(range(n))
    sz = [1] * n
    
    def find(i):
        path = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for node in path:
            parent[node] = i
        return i

    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            if sz[root_i] < sz[root_j]:
                root_i, root_j = root_j, root_i
            parent[root_j] = root_i
            sz[root_i] += sz[root_j]

    for i in range(n):
        for j in range(i + 1, n):
            if intersect(segs[i], segs[j]):
                union(i, j)
                
    groups = set()
    max_size = 0
    for i in range(n):
        r = find(i)
        groups.add(r)
        if sz[r] > max_size:
            max_size = sz[r]
            
    print(len(groups))
    print(max_size)

if __name__ == '__main__':
    main()
