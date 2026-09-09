"""
ZeliJudge Junior Problem #002: 거꾸로 말해요! 마법 비밀 암호
Standard Solution (Python 3)
"""
import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    print(line[::-1])

if __name__ == "__main__":
    main()
