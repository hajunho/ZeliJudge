import sys

def count_bubble_swaps(arr):
    a = list(arr)
    n = len(a)
    swaps = 0
    for i in range(n):
        for j in range(0, n - 1 - i):
            if a[j] > a[j + 1]:
                a[j], a[j + 1] = a[j + 1], a[j]
                swaps += 1
    return swaps

def count_selection_swaps(arr):
    a = list(arr)
    n = len(a)
    swaps = 0
    for i in range(n - 1):
        min_idx = i
        for j in range(i + 1, n):
            if a[j] < a[min_idx]:
                min_idx = j
        if min_idx != i:
            a[i], a[min_idx] = a[min_idx], a[i]
            swaps += 1
    return swaps

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    nums = [int(x) for x in tokens[1:1+n]]
    
    b_swaps = count_bubble_swaps(nums)
    s_swaps = count_selection_swaps(nums)
    print(f"{b_swaps} {s_swaps}")

if __name__ == "__main__":
    main()
