"""
ZeliJudge Junior Problem #044: 보물섬 나침반과 4방향 최종 좌표
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    m = int(lines[0].strip())
    
    x = 0
    y = 0
    
    for i in range(1, 1 + m):
        parts = lines[i].split()
        direction = parts[0]
        step = int(parts[1])
        
        if direction == 'E':
            x += step
        elif direction == 'W':
            x -= step
        elif direction == 'N':
            y += step
        elif direction == 'S':
            y -= step
            
    print(f"{x} {y}")

if __name__ == "__main__":
    main()
