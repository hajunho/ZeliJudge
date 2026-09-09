import sys

ROMAN_MAP = {
    'I': 1, 'V': 5, 'X': 10, 'L': 50,
    'C': 100, 'D': 500, 'M': 1000
}

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
    total = 0
    n = len(s)
    for i in range(n):
        val = ROMAN_MAP[s[i]]
        if i + 1 < n and val < ROMAN_MAP[s[i + 1]]:
            total -= val
        else:
            total += val
    print(total)

if __name__ == "__main__":
    main()
