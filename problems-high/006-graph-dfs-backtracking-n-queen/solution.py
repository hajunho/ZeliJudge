import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    
    cols = [False] * n
    diag1 = [False] * (2 * n)     # r + c
    diag2 = [False] * (2 * n)     # r - c + n
    
    count = 0
    
    def dfs(r):
        nonlocal count
        if r == n:
            count += 1
            return
            
        for c in range(n):
            if not cols[c] and not diag1[r + c] and not diag2[r - c + n]:
                cols[c] = diag1[r + c] = diag2[r - c + n] = True
                dfs(r + 1)
                cols[c] = diag1[r + c] = diag2[r - c + n] = False

    dfs(0)
    print(count)

if __name__ == "__main__":
    solve()
