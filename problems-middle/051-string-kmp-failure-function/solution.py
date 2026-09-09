import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    P = lines[0]
    n = len(P)
    pi = [0] * n
    j = 0
    for i in range(1, n):
        while j > 0 and P[i] != P[j]:
            j = pi[j - 1]
        if P[i] == P[j]:
            j += 1
            pi[i] = j
    print(" ".join(map(str, pi)))

if __name__ == "__main__":
    solve()
