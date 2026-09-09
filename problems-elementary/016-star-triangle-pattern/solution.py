"""
ZeliJudge Junior Problem #016: 밤하늘을 수놓는 별빛 삼각형 아트
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    for i in range(1, n + 1):
        print("*" * i)

if __name__ == "__main__":
    main()
