"""
ZeliJudge Junior Problem #023: 보드게임 주사위 2개의 눈금 합 맞추기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    k = int(tokens[0])
    
    pairs = []
    for a in range(1, 7):
        for b in range(1, 7):
            if a + b == k:
                pairs.append((a, b))
                
    print(len(pairs))
    for a, b in pairs:
        print(f"{a} {b}")

if __name__ == "__main__":
    main()
