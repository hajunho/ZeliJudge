"""
ZeliJudge Junior Problem #027: 한 자리 숫자가 될 때까지 자릿수 더하기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    while n >= 10:
        total = 0
        for digit in str(n):
            total += int(digit)
        n = total
        
    print(n)

if __name__ == "__main__":
    main()
