import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    m = int(input_data[0])
    c1 = float(input_data[1])
    c2 = float(input_data[2])
    
    constraints = []
    idx = 3
    for _ in range(m):
        a1 = float(input_data[idx])
        a2 = float(input_data[idx+1])
        b = float(input_data[idx+2])
        idx += 3
        constraints.append((a1, a2, b))
        
    # Since it is 2-variable LP, optimal vertex is either:
    # 1. (0, 0)
    # 2. Intersections with x1 = 0 axis: (0, b/a2)
    # 3. Intersections with x2 = 0 axis: (b/a1, 0)
    # 4. Intersections between two constraint lines
    vertices = [(0.0, 0.0)]
    
    for a1, a2, b in constraints:
        if a2 > 1e-9:
            vertices.append((0.0, b / a2))
        if a1 > 1e-9:
            vertices.append((b / a1, 0.0))
            
    for i in range(m):
        for j in range(i + 1, m):
            a11, a12, b1 = constraints[i]
            a21, a22, b2 = constraints[j]
            det = a11 * a22 - a12 * a21
            if abs(det) > 1e-9:
                x1 = (b1 * a22 - b2 * a12) / det
                x2 = (a11 * b2 - a21 * b1) / det
                if x1 >= -1e-9 and x2 >= -1e-9:
                    vertices.append((max(0.0, x1), max(0.0, x2)))
                    
    max_val = 0.0
    for x1, x2 in vertices:
        # Check feasibility
        feasible = True
        for a1, a2, b in constraints:
            if a1 * x1 + a2 * x2 > b + 1e-7:
                feasible = False
                break
        if feasible:
            val = c1 * x1 + c2 * x2
            if val > max_val:
                max_val = val
                
    print(f"{max_val:.2f}")

if __name__ == '__main__':
    solve()
