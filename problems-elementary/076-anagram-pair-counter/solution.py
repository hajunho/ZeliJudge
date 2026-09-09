import sys
from collections import Counter

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    words = tokens[1:1+n]
    
    canonical = []
    for w in words:
        canonical.append("".join(sorted(w)))
        
    counts = Counter(canonical)
    pairs = 0
    for count in counts.values():
        if count >= 2:
            pairs += count * (count - 1) // 2
            
    print(pairs)

if __name__ == "__main__":
    main()
