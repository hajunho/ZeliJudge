import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    
    if n == 1:
        print(1)
        print(1)
        return
        
    parents_set = set()
    for i in range(1, n):
        parts = lines[i].split()
        p = int(parts[0])
        parents_set.add(p)
        
    leaves = [node for node in range(1, n + 1) if node not in parents_set]
    leaves.sort()
    
    print(len(leaves))
    print(" ".join(map(str, leaves)))

if __name__ == "__main__":
    main()
