import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    n, k = int(parts[0]), int(parts[1])
    
    if k == 1:
        print(0)
        return
        
    parent = {}
    for line in lines[1:n]:
        if not line.strip():
            continue
        p, c = map(int, line.split())
        parent[c] = p
        
    depth = 0
    curr = k
    while curr != 1 and curr in parent:
        curr = parent[curr]
        depth += 1
        
    print(depth)

if __name__ == "__main__":
    main()
