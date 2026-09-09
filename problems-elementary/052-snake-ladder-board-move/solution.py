"""
ZeliJudge Junior Problem #052: 뱀과 사다리 게임의 말판 점프 시뮬레이션
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    k = int(lines[0].strip())
    
    portals = {}
    line_idx = 1
    for _ in range(k):
        parts = lines[line_idx].split()
        u, v = int(parts[0]), int(parts[1])
        portals[u] = v
        line_idx += 1
        
    t = int(lines[line_idx].strip())
    line_idx += 1
    dice = [int(x) for x in lines[line_idx].split()]
    
    pos = 1
    for d in dice:
        pos += d
        if pos > 30:
            pos = 30
        if pos in portals:
            pos = portals[pos]
            
    print(pos)

if __name__ == "__main__":
    main()
