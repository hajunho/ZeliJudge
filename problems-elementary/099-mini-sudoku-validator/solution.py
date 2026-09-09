import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    grid = []
    for i in range(4):
        grid.append([int(x) for x in lines[i].split()])
        
    target = {1, 2, 3, 4}
    # 행 검사
    for r in range(4):
        if set(grid[r]) != target:
            print("NO")
            return
            
    # 열 검사
    for c in range(4):
        col_set = {grid[r][c] for r in range(4)}
        if col_set != target:
            print("NO")
            return
            
    print("YES")

if __name__ == "__main__":
    main()
