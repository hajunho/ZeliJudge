import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c = int(parts[0]), int(parts[1])
    
    grid = []
    for i in range(1, 1 + r):
        grid.append([int(x) for x in lines[i].split()])
        
    max_sum = -float('inf')
    for i in range(1, r - 1):
        for j in range(1, c - 1):
            cross_sum = (grid[i][j] +
                         grid[i - 1][j] + grid[i + 1][j] +
                         grid[i][j - 1] + grid[i][j + 1])
            if cross_sum > max_sum:
                max_sum = cross_sum
                
    print(max_sum)

if __name__ == "__main__":
    main()
