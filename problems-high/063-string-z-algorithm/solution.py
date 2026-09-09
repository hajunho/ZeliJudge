import sys

def z_algorithm(s):
    n = len(s)
    z = [0] * n
    z[0] = n
    l = 0
    r = 0
    for i in range(1, n):
        if i <= r:
            k = i - l
            if z[k] < r - i + 1:
                z[i] = z[k]
            else:
                l = i
                while r < n and s[r] == s[r - l]:
                    r += 1
                z[i] = r - l
                r -= 1
        else:
            l = i
            r = i
            while r < n and s[r] == s[r - l]:
                r += 1
            z[i] = r - l
            r -= 1
    return z

def main():
    s = sys.stdin.read().strip()
    if not s:
        return
    z = z_algorithm(s)
    print(' '.join(map(str, z)))

if __name__ == '__main__':
    main()
