"""
ZeliJudge Junior Problem #011: 문구점 거스름돈과 최소 동전 개수
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    m = int(tokens[0])
    
    c500 = m // 500
    m %= 500
    
    c100 = m // 100
    m %= 100
    
    c50 = m // 50
    m %= 50
    
    c10 = m // 10
    
    print(f"{c500} {c100} {c50} {c10}")

if __name__ == "__main__":
    main()
