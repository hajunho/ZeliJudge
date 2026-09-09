import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    words = line.split()
    reversed_words = words[::-1]
    print(" ".join(reversed_words))

if __name__ == "__main__":
    main()
