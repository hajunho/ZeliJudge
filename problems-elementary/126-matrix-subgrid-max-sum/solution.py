import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    r, c = map(int, lines[0].split())
    grid = []
    for i in range(1, 1 + r):
        grid.append([int(x) for x in lines[i].split()])
        
    max_sum = -float('inf')
    for i in range(r - 1):
        for j in range(c - 1):
            sub_sum = (grid[i][j] + grid[i][j + 1] +
                       grid[i + 1][j] + grid[i + 1][j + 1])
            if sub_sum > max_sum:
                max_sum = sub_sum
                
    print(max_sum)

if __name__ == "__main__":
    main()
