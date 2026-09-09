"""
ZeliJudge Junior Problem #054: 마법 거울에 비친 행렬 뒤집기 (전치행렬)
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    first = lines[0].split()
    r = int(first[0])
    c = int(first[1])
    
    grid = []
    for i in range(r):
        grid.append(lines[1 + i].split())
        
    for col in range(c):
        col_vals = [grid[row][col] for row in range(r)]
        print(" ".join(col_vals))

if __name__ == "__main__":
    main()
