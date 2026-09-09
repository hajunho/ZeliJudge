import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    idx = 1
    # Augmented matrix A of size N x (N + 1)
    A = []
    for _ in range(N):
        row = [float(x) for x in lines[idx:idx+N+1]]
        A.append(row)
        idx += N + 1
        
    # Forward Elimination with Partial Pivoting
    for i in range(N):
        # Find pivot
        max_row = i
        max_val = abs(A[i][i])
        for r in range(i + 1, N):
            if abs(A[r][i]) > max_val:
                max_val = abs(A[r][i])
                max_row = r
                
        A[i], A[max_row] = A[max_row], A[i]
        
        pivot = A[i][i]
        for c in range(i, N + 1):
            A[i][c] /= pivot
            
        for r in range(i + 1, N):
            factor = A[r][i]
            for c in range(i, N + 1):
                A[r][c] -= factor * A[i][c]
                
    # Back Substitution
    ans = [0.0] * N
    for i in range(N - 1, -1, -1):
        ans[i] = A[i][N]
        for c in range(i + 1, N):
            ans[i] -= A[i][c] * ans[c]
            
    # Format to 2 decimal places
    out = [f"{x:.2f}" for x in ans]
    print(' '.join(out))

if __name__ == "__main__":
    solve()
