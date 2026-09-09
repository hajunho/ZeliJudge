import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c = int(parts[0]), int(parts[1])
    
    board = [list(lines[1 + i].strip()) for i in range(r)]
    
    dr = [-1, -1, -1, 0, 0, 1, 1, 1]
    dc = [-1, 0, 1, -1, 1, -1, 0, 1]
    
    for i in range(r):
        for j in range(c):
            if board[i][j] == '.':
                cnt = 0
                for d in range(8):
                    ni = i + dr[d]
                    nj = j + dc[d]
                    if 0 <= ni < r and 0 <= nj < c and board[ni][nj] == '*':
                        cnt += 1
                board[i][j] = str(cnt)
                
    for row in board:
        print("".join(row))

if __name__ == "__main__":
    main()
