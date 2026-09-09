import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    s = lines[0].strip()
    t = lines[1].strip()
    
    j = 0
    len_t = len(t)
    for ch in s:
        if ch == t[j]:
            j += 1
            if j == len_t:
                break
                
    if j == len_t:
        print("YES")
    else:
        print("NO")

if __name__ == "__main__":
    main()
