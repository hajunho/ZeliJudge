"""
ZeliJudge Junior Problem #022: 마법사의 레벨업과 팩토리얼(!) 계산기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    ans = 1
    for i in range(1, n + 1):
        ans *= i
        
    print(ans)

if __name__ == "__main__":
    main()
