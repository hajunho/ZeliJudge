import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    
    depth = [0] * (n + 1)
    depth[1] = 1
    
    parents = [int(x) for x in tokens[1:n]]
    for idx, p in enumerate(parents):
        person = idx + 2
        depth[person] = depth[p] + 1
        
    print(" ".join(map(str, depth[1:n+1])))

if __name__ == "__main__":
    main()
