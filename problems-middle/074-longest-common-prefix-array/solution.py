import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    words = lines[1:1+N]
    
    # Sort lexicographically
    words.sort()
    
    # Compute LCP of adjacent words
    lcp = []
    for i in range(N - 1):
        w1 = words[i]
        w2 = words[i+1]
        common = 0
        limit = min(len(w1), len(w2))
        while common < limit and w1[common] == w2[common]:
            common += 1
        lcp.append(common)
        
    print(' '.join(words))
    print(' '.join(map(str, lcp)))

if __name__ == "__main__":
    solve()
