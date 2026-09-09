import sys

def solve():
    lines = sys.stdin.read().split()
    if not lines:
        return
    N = int(lines[0])
    arr = [int(x) for x in lines[1:1+N]]
    
    def sift_down(arr, n, i):
        largest = i
        l = 2 * i + 1
        r = 2 * i + 2
        
        if l < n and arr[l] > arr[largest]:
            largest = l
        if r < n and arr[r] > arr[largest]:
            largest = r
            
        if largest != i:
            arr[i], arr[largest] = arr[largest], arr[i]
            sift_down(arr, n, largest)
            
    # Step 1: Build Max Heap
    for i in range(N // 2 - 1, -1, -1):
        sift_down(arr, N, i)
        
    heap_state = list(arr)
    
    # Step 2: Extract elements one by one
    for i in range(N - 1, 0, -1):
        arr[0], arr[i] = arr[i], arr[0]
        sift_down(arr, i, 0)
        
    print(' '.join(map(str, heap_state)))
    print(' '.join(map(str, arr)))

if __name__ == "__main__":
    solve()
