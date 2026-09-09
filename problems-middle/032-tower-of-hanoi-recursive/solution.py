import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    
    moves = []
    def hanoi(n, src, dst, aux):
        if n == 1:
            moves.append(f"{src} {dst}")
            return
        hanoi(n - 1, src, aux, dst)
        moves.append(f"{src} {dst}")
        hanoi(n - 1, aux, dst, src)
        
    hanoi(N, 1, 3, 2)
    print(len(moves))
    for m in moves:
        print(m)

if __name__ == "__main__":
    solve()
