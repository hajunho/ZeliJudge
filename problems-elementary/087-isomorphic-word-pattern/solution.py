import sys

def is_isomorphic(s, t):
    if len(s) != len(t):
        return False
    s2t = {}
    t2s = {}
    for c1, c2 in zip(s, t):
        if c1 in s2t and s2t[c1] != c2:
            return False
        if c2 in t2s and t2s[c2] != c1:
            return False
        s2t[c1] = c2
        t2s[c2] = c1
    return True

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    s = lines[0].strip()
    t = lines[1].strip()
    if is_isomorphic(s, t):
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
