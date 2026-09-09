"""
ZeliJudge Junior Problem #034: 교실 빙고 게임! 몇 줄 완성했니?
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
        
    grid = []
    for i in range(3):
        grid.append(lines[i].split())
        
    bingo = 0
    
    # 가로 3줄 검사
    for r in range(3):
        if grid[r][0] == 'O' and grid[r][1] == 'O' and grid[r][2] == 'O':
            bingo += 1
            
    # 세로 3줄 검사
    for c in range(3):
        if grid[0][c] == 'O' and grid[1][c] == 'O' and grid[2][c] == 'O':
            bingo += 1
            
    # 대각선 2줄 검사
    if grid[0][0] == 'O' and grid[1][1] == 'O' and grid[2][2] == 'O':
        bingo += 1
    if grid[0][2] == 'O' and grid[1][1] == 'O' and grid[2][0] == 'O':
        bingo += 1
        
    print(bingo)

if __name__ == "__main__":
    main()
