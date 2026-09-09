import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    piles = [int(x) for x in lines[1:1+N]]
    
    # Nim-sum is the XOR sum of all pile sizes
    nim_sum = 0
    for p in piles:
        nim_sum ^= p
        
    if nim_sum != 0:
        print("FIRST")
    else:
        print("SECOND")

if __name__ == "__main__":
    solve()
