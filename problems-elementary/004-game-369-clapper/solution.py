"""
ZeliJudge Junior Problem #004: 3·6·9 박수 게임 심판관
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    for i in range(1, n + 1):
        s = str(i)
        claps = s.count('3') + s.count('6') + s.count('9')
        if claps > 0:
            print("-".join(["CLAP"] * claps))
        else:
            print(i)

if __name__ == "__main__":
    main()
