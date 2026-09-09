"""
ZeliJudge Junior Problem #006: 삐리비리! 스마트 청소 로봇의 하루
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    
    first = lines[0].split()
    h = int(first[0])
    w = int(first[1])
    
    grid = []
    line_idx = 1
    for _ in range(h):
        grid.append(lines[line_idx])
        line_idx += 1
        
    start_pos = lines[line_idx].split()
    r = int(start_pos[0]) - 1 # 0-indexed
    c = int(start_pos[1]) - 1
    line_idx += 1
    
    commands = lines[line_idx].strip()
    
    moves = {
        'U': (-1, 0),
        'D': (1, 0),
        'L': (0, -1),
        'R': (0, 1)
    }
    
    for cmd in commands:
        if cmd in moves:
            dr, dc = moves[cmd]
            nr, nc = r + dr, c + dc
            # 경계 검사 및 벽 검사
            if 0 <= nr < h and 0 <= nc < w:
                if grid[nr][nc] != '#':
                    r, c = nr, nc
                    
    print(f"{r + 1} {c + 1}")

if __name__ == "__main__":
    main()
