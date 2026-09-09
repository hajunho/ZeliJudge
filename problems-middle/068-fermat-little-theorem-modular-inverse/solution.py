import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    A = int(lines[0])
    B = int(lines[1])
    P = int(lines[2])
    
    inv_B = pow(B, P - 2, P)
    ans = (A * inv_B) % P
    print(ans)

if __name__ == "__main__":
    solve()
