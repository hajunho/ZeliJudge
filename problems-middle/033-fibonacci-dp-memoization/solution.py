import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    MOD = 1000000007
    if N == 0:
        print(0)
        return
    if N == 1:
        print(1)
        return
    
    a, b = 0, 1
    for _ in range(2, N + 1):
        a, b = b, (a + b) % MOD
    print(b)

if __name__ == "__main__":
    solve()
