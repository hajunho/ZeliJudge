"""
ZeliJudge Junior Problem #038: 매일매일 연속 출석왕 챌린지
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    records = tokens[1:1+n]
    
    current_streak = 0
    max_streak = 0
    
    for r in records:
        if r == 'O':
            current_streak += 1
            if current_streak > max_streak:
                max_streak = current_streak
        else:
            current_streak = 0
            
    print(max_streak)

if __name__ == "__main__":
    main()
