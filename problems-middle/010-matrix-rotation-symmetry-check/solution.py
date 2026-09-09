import sys

def rotate_90(matrix, n):
    rotated = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            rotated[c][n - 1 - r] = matrix[r][c]
    return rotated

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    grid = []
    for i in range(1, 1 + n):
        grid.append([int(x) for x in lines[i].split()])
        
    r90 = rotate_90(grid, n)
    r180 = rotate_90(r90, n)
    r270 = rotate_90(r180, n)
    
    is_90 = "YES" if grid == r90 else "NO"
    is_180 = "YES" if grid == r180 else "NO"
    is_270 = "YES" if grid == r270 else "NO"
    
    print(f"{is_90} {is_180} {is_270}")

if __name__ == "__main__":
    main()
