"""
ZeliJudge Junior Problem #043: 가로 세로 대각선이 모두 같은 3x3 마방진 검사기
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
        
    grid = []
    for i in range(3):
        grid.append([int(x) for x in lines[i].split()])
        
    sums = []
    # 가로 3줄
    for r in range(3):
        sums.append(sum(grid[r]))
    # 세로 3줄
    for c in range(3):
        sums.append(grid[0][c] + grid[1][c] + grid[2][c])
    # 대각선 2줄
    sums.append(grid[0][0] + grid[1][1] + grid[2][2])
    sums.append(grid[0][2] + grid[1][1] + grid[2][0])
    
    # 8개의 합이 전부 같은지 검사
    if len(set(sums)) == 1:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
