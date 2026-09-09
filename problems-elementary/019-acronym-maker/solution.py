"""
ZeliJudge Junior Problem #019: 유행어 만들기! 앞 글자만 딴 마법 줄임말
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
        
    acronym = []
    for word in tokens:
        acronym.append(word[0].upper())
        
    print("".join(acronym))

if __name__ == "__main__":
    main()
