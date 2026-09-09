"""
ZeliJudge Junior Problem #033: 사탕과 초콜릿 남김없이 포장하기 (최대공약수)
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
    
    print(math.gcd(a, b))

if __name__ == "__main__":
    main()
