import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    grid = []
    for i in range(1, 1 + n):
        grid.append(lines[i].split())
        
    for i in range(n):
        for j in range(i + 1, n):
            if grid[i][j] != grid[j][i]:
                print("NO")
                return
                
    print("YES")

if __name__ == "__main__":
    main()
