"""
ZeliJudge Junior Problem #012: 가위바위보 챔피언십 승패 판정기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    a = tokens[0]
    b = tokens[1]
    
    if a == b:
        print("DRAW")
    elif (a == "R" and b == "S") or (a == "S" and b == "P") or (a == "P" and b == "R"):
        print("A")
    else:
        print("B")

if __name__ == "__main__":
    main()
