import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    k = int(input_data[0])
    n = int(input_data[1])
    cables = [int(x) for x in input_data[2:2+k]]
    
    left = 1
    right = max(cables)
    answer = 0
    
    while left <= right:
        mid = (left + right) // 2
        count = sum(c // mid for c in cables)
        if count >= n:
            answer = mid
            left = mid + 1
        else:
            right = mid - 1
            
    print(answer)

if __name__ == "__main__":
    solve()
