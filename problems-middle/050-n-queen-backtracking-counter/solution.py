import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    
    col = [False] * N
    diag1 = [False] * (2 * N)  # r + c
    diag2 = [False] * (2 * N)  # r - c + N
    
    count = 0
    def backtrack(r):
        nonlocal count
        if r == N:
            count += 1
            return
        for c in range(N):
            if not col[c] and not diag1[r + c] and not diag2[r - c + N]:
                col[c] = diag1[r + c] = diag2[r - c + N] = True
                backtrack(r + 1)
                col[c] = diag1[r + c] = diag2[r - c + N] = False
                
    backtrack(0)
    print(count)

if __name__ == "__main__":
    solve()
