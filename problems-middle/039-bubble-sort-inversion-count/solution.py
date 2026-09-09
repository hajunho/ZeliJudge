import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    arr = [int(x) for x in lines[1:N+1]]
    
    swap_count = 0
    for i in range(N):
        for j in range(N - 1 - i):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swap_count += 1
    print(swap_count)

if __name__ == "__main__":
    solve()
