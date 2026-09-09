"""
ZeliJudge Junior Problem #015: 수학 천재 가우스의 1부터 N까지 연속 덧셈
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    total = n * (n + 1) // 2
    print(total)

if __name__ == "__main__":
    main()
