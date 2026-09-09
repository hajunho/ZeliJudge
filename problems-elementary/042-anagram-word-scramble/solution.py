"""
ZeliJudge Junior Problem #042: 뒤죽박죽 글자 섞기! 아나그램(Anagram) 탐정
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    w1 = lines[0].strip()
    w2 = lines[1].strip()
    
    if sorted(w1) == sorted(w2):
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
