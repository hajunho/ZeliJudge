import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    r, c = map(int, line.split())
    
    grid = [[0] * c for _ in range(r)]
    top, bottom = 0, r - 1
    left, right = 0, c - 1
    num = 1
    
    while top <= bottom and left <= right:
        # 1. 오른쪽으로
        for j in range(left, right + 1):
            grid[top][j] = num
            num += 1
        top += 1
        
        # 2. 아래쪽으로
        for i in range(top, bottom + 1):
            grid[i][right] = num
            num += 1
        right -= 1
        
        # 3. 왼쪽으로
        if top <= bottom:
            for j in range(right, left - 1, -1):
                grid[bottom][j] = num
                num += 1
            bottom -= 1
            
        # 4. 위쪽으로
        if left <= right:
            for i in range(bottom, top - 1, -1):
                grid[i][left] = num
                num += 1
            left += 1
            
    for row in grid:
        print(" ".join(str(x) for x in row))

if __name__ == "__main__":
    main()
