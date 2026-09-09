"""
ZeliJudge Junior Problem #035: 마법진의 대각선 에너지 합 구하기
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    total = 0
    for i in range(n):
        row = [int(x) for x in lines[1 + i].split()]
        total += row[i]
        
    print(total)

if __name__ == "__main__":
    main()
