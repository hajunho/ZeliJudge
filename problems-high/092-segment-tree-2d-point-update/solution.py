import sys

# 2D Fenwick Tree (Binary Indexed Tree) is optimal and standard for 2D Point Update Range Sum
class Fenwick2D:
    def __init__(self, r, c):
        self.r = r
        self.c = c
        self.tree = [[0] * (c + 1) for _ in range(r + 1)]
        
    def add(self, row, col, val):
        i = row
        while i <= self.r:
            j = col
            while j <= self.c:
                self.tree[i][j] += val
                j += j & (-j)
            i += i & (-i)
            
    def query_prefix(self, row, col):
        res = 0
        i = row
        while i > 0:
            j = col
            while j > 0:
                res += self.tree[i][j]
                j -= j & (-j)
            i -= i & (-i)
        return res
        
    def query_rect(self, r1, c1, r2, c2):
        return (self.query_prefix(r2, c2) 
                - self.query_prefix(r1 - 1, c2) 
                - self.query_prefix(r2, c1 - 1) 
                + self.query_prefix(r1 - 1, c1 - 1))

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    r = int(input_data[0])
    c = int(input_data[1])
    q = int(input_data[2])
    
    bit = Fenwick2D(r, c)
    val_grid = [[0] * (c + 1) for _ in range(r + 1)]
    
    idx = 3
    for i in range(1, r + 1):
        for j in range(1, c + 1):
            val = int(input_data[idx])
            val_grid[i][j] = val
            bit.add(i, j, val)
            idx += 1
            
    out = []
    for _ in range(q):
        t = int(input_data[idx])
        if t == 1:
            row = int(input_data[idx + 1])
            col = int(input_data[idx + 2])
            new_val = int(input_data[idx + 3])
            idx += 4
            diff = new_val - val_grid[row][col]
            val_grid[row][col] = new_val
            bit.add(row, col, diff)
        else:
            r1 = int(input_data[idx + 1])
            c1 = int(input_data[idx + 2])
            r2 = int(input_data[idx + 3])
            c2 = int(input_data[idx + 4])
            idx += 5
            out.append(str(bit.query_rect(r1, c1, r2, c2)))
            
    print('\n'.join(out))

if __name__ == '__main__':
    main()
