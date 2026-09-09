import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    scores = [int(x) for x in lines[1].split()]
    scores.sort()
    print(scores[n // 2])

if __name__ == "__main__":
    main()
