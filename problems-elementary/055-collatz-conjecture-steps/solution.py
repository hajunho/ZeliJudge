"""
ZeliJudge Junior Problem #055: 우박처럼 오르락내리락! 콜라츠 추측(우박수)
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    steps = 0
    while n > 1:
        if n % 2 == 0:
            n //= 2
        else:
            n = 3 * n + 1
        steps += 1
        
    print(steps)

if __name__ == "__main__":
    main()
