"""
ZeliJudge Junior Problem #024: 피자 조각 나누기와 최소 피자 판 수 구하기
Standard Solution (Python 3)
"""
import sys
import math

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    s = int(tokens[1])
    
    total_slices = n * s
    # 8조각으로 나누어 올림
    pizzas = math.ceil(total_slices / 8)
    print(pizzas)

if __name__ == "__main__":
    main()
