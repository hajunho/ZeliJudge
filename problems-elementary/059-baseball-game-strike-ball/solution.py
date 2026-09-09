"""
ZeliJudge Junior Problem #059: 컴퓨터와 대결하는 숫자 야구 게임 (스트라이크 & 볼)
Standard Solution (Python 3)
"""
import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    secret = lines[0].strip()
    guess = lines[1].strip()
    
    strikes = 0
    balls = 0
    
    for i in range(3):
        if guess[i] == secret[i]:
            strikes += 1
        elif guess[i] in secret:
            balls += 1
            
    print(f"{strikes}S {balls}B")

if __name__ == "__main__":
    main()
