import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n, x = map(int, lines[0].split())
    arr = [int(v) for v in lines[1].split()]
    
    low = 0
    high = n - 1
    found_idx = -1
    
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == x:
            found_idx = mid + 1  # 1-based index
            break
        elif arr[mid] < x:
            low = mid + 1
        else:
            high = mid - 1
            
    print(found_idx)

if __name__ == "__main__":
    main()
