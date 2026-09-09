"""
ZeliJudge Junior Problem #047: 두 노선 버스가 동시에 정류장에 오는 시간 (최소공배수)
Standard Solution (Python 3)
"""
import sys
import math

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    a = int(tokens[0])
    b = int(tokens[1])
    
    # math.lcm은 Python 3.9+ 지원
    ans = math.lcm(a, b)
    print(ans)

if __name__ == "__main__":
    main()
