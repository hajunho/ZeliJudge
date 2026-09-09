import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    A = []
    for _ in range(N):
        row = [float(x) for x in lines[idx:idx+N]]
        A.append(row)
        idx += N
        
    det = 1.0
    sign = 1
    
    # Gaussian Elimination to Upper Triangular Matrix
    for i in range(N):
        # Pivot selection
        pivot_row = i
        max_val = abs(A[i][i])
        for r in range(i + 1, N):
            if abs(A[r][i]) > max_val:
                max_val = abs(A[r][i])
                pivot_row = r
                
        if max_val < 1e-12:
            print("0.0")
            return
            
        if pivot_row != i:
            A[i], A[pivot_row] = A[pivot_row], A[i]
            sign = -sign
            
        det *= A[i][i]
        
        for r in range(i + 1, N):
            factor = A[r][i] / A[i][i]
            for c in range(i, N):
                A[r][c] -= factor * A[i][c]
                
    ans = sign * det
    if abs(ans) < 1e-9:
        ans = 0.0
    print(f"{ans:.1f}")

if __name__ == "__main__":
    solve()
