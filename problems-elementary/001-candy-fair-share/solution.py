"""
ZeliJudge Junior Problem #001: 생일 파티 사탕 공평하게 나누기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    c = int(tokens[1])
    
    share = c // n
    remainder = c % n
    print(f"{share} {remainder}")

if __name__ == "__main__":
    main()
