"""
ZeliJudge Junior Problem #008: 앞으로 읽어도 뒤로 읽어도 똑같은 거울 단어
Standard Solution (Python 3)
"""
import sys

def main():
    word = sys.stdin.read().strip()
    if not word:
        return
    
    if word == word[::-1]:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
