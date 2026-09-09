import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    H = [int(x) for x in lines[1:1+N]]
    
    left = 0
    right = N - 1
    max_area = 0
    best_l = 0
    best_r = 0
    
    while left < right:
        width = right - left
        height = min(H[left], H[right])
        area = width * height
        if area > max_area:
            max_area = area
            best_l = left + 1 # 1-based
            best_r = right + 1
            
        if H[left] < H[right]:
            left += 1
        else:
            right -= 1
            
    print(max_area)
    print(f"{best_l} {best_r}")

if __name__ == "__main__":
    solve()
