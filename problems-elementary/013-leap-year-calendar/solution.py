"""
ZeliJudge Junior Problem #013: 4년에 한 번! 2월 29일 윤년 판독기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    year = int(tokens[0])
    
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        print("LEAP")
    else:
        print("COMMON")

if __name__ == "__main__":
    main()
