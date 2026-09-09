"""
ZeliJudge Junior Problem #005: 소풍 기념 사진! 키 순서대로 줄 서기
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    heights = [int(x) for x in tokens[1:1+n]]
    
    min_val = min(heights)
    max_val = max(heights)
    sorted_heights = sorted(heights)
    
    print(f"{min_val} {max_val}")
    print(" ".join(map(str, sorted_heights)))

if __name__ == "__main__":
    main()
