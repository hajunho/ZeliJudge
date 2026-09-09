import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    M = int(lines[1])
    trees = [int(x) for x in lines[2:2+N]]
    
    low = 0
    high = max(trees)
    ans = 0
    while low <= high:
        mid = (low + high) // 2
        wood = sum(h - mid for h in trees if h > mid)
        if wood >= M:
            ans = mid
            low = mid + 1
        else:
            high = mid - 1
    print(ans)

if __name__ == "__main__":
    solve()
