import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    M = int(lines[1])
    K = int(lines[2])
    idx = 3
    
    diff = [[0] * (M + 2) for _ in range(N + 2)]
    for _ in range(K):
        r1 = int(lines[idx])
        c1 = int(lines[idx+1])
        r2 = int(lines[idx+2])
        c2 = int(lines[idx+3])
        idx += 4
        diff[r1][c1] += 1
        diff[r1][c2 + 1] -= 1
        diff[r2 + 1][c1] -= 1
        diff[r2 + 1][c2 + 1] += 1
        
    max_val = 0
    for r in range(1, N + 1):
        for c in range(1, M + 1):
            diff[r][c] += diff[r - 1][c] + diff[r][c - 1] - diff[r - 1][c - 1]
            if diff[r][c] > max_val:
                max_val = diff[r][c]
    print(max_val)

if __name__ == "__main__":
    solve()
