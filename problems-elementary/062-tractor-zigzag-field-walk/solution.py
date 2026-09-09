import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    rc = lines[0].split()
    r, c = int(rc[0]), int(rc[1])
    
    result = []
    for i in range(r):
        row = lines[1 + i].split()
        if i % 2 == 0:
            result.extend(row)
        else:
            result.extend(reversed(row))
            
    print(" ".join(result))

if __name__ == "__main__":
    main()
