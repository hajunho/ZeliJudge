"""
ZeliJudge Junior Problem #050: 전설의 황금 원판 옮기기! 하노이의 탑 최소 이동 횟수
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    moves = (2 ** n) - 1
    print(moves)

if __name__ == "__main__":
    main()
