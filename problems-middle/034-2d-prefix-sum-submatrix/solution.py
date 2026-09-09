import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    N = int(input_data[0])
    M = int(input_data[1])
    Q = int(input_data[2])
    idx = 3
    
    grid = []
    for _ in range(N):
        row = []
        for _ in range(M):
            row.append(int(input_data[idx]))
            idx += 1
        grid.append(row)
        
    S = [[0] * (M + 1) for _ in range(N + 1)]
    for r in range(1, N + 1):
        for c in range(1, M + 1):
            S[r][c] = grid[r-1][c-1] + S[r-1][c] + S[r][c-1] - S[r-1][c-1]
            
    out = []
    for _ in range(Q):
        r1 = int(input_data[idx])
        c1 = int(input_data[idx+1])
        r2 = int(input_data[idx+2])
        c2 = int(input_data[idx+3])
        idx += 4
        ans = S[r2][c2] - S[r1-1][c2] - S[r2][c1-1] + S[r1-1][c1-1]
        out.append(str(ans))
    print("\n".join(out))

if __name__ == "__main__":
    solve()
