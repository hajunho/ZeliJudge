import sys

def main():
    line = sys.stdin.read().strip()
    if not line:
        return
    words = line.split()
    capitalized = [w.capitalize() for w in words]
    print(" ".join(capitalized))

if __name__ == "__main__":
    main()
