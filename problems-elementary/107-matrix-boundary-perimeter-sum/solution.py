import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].split()
    r, c = int(parts[0]), int(parts[1])
    
    total = 0
    for i in range(r):
        row = [int(x) for x in lines[1 + i].split()]
        for j in range(c):
            if i == 0 or i == r - 1 or j == 0 or j == c - 1:
                total += row[j]
                
    print(total)

if __name__ == "__main__":
    main()
