"""
ZeliJudge Junior Problem #029: 거꾸로 읽어도 똑같은 회문 숫자 찾기
Standard Solution (Python 3)
"""
import sys

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
        
    if s == s[::-1]:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
