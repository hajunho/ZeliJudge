"""
ZeliJudge Junior Problem #051: 약수들의 합이 나와 같은 완벽한 숫자 (완전수)
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    if n <= 1:
        print("NOT_PERFECT")
        return
        
    div_sum = 0
    for i in range(1, n):
        if n % i == 0:
            div_sum += i
            
    if div_sum == n:
        print("PERFECT")
    else:
        print("NOT_PERFECT")

if __name__ == "__main__":
    main()
