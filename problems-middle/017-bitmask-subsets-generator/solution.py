import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    elements = lines[1].split()
    
    total_subsets = 1 << n  # 2^n
    out = []
    for mask in range(total_subsets):
        subset = []
        for i in range(n):
            if mask & (1 << i):
                subset.append(elements[i])
        out.append(" ".join(subset))
        
    print("\n".join(out))

if __name__ == "__main__":
    main()
