"""
ZeliJudge Junior Problem #036: 동화책 속 가장 많이 등장한 단어 찾기
Standard Solution (Python 3)
"""
import sys

def main():
    words = sys.stdin.read().split()
    if not words:
        return
        
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
        
    max_freq = max(counts.values())
    candidates = [w for w, freq in counts.items() if freq == max_freq]
    candidates.sort()
    
    print(f"{candidates[0]} {max_freq}")

if __name__ == "__main__":
    main()
