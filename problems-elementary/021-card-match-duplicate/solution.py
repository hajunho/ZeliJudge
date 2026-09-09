"""
ZeliJudge Junior Problem #021: 보물찾기 카드 짝 맞추기와 중복 제거
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    cards = tokens[1:1+n]
    
    unique_cards = sorted(list(set(cards)))
    print(len(unique_cards))
    print(" ".join(unique_cards))

if __name__ == "__main__":
    main()
