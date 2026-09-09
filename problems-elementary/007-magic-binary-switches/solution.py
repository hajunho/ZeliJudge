"""
ZeliJudge Junior Problem #007: 보물 상자를 여는 4개의 전구 스위치
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    
    b8 = int(tokens[0])
    b4 = int(tokens[1])
    b2 = int(tokens[2])
    b1 = int(tokens[3])
    
    total = b8 * 8 + b4 * 4 + b2 * 2 + b1 * 1
    print(total)

if __name__ == "__main__":
    main()
