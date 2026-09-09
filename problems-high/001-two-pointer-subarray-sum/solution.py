import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    count = 0
    current_sum = 0
    right = 0
    
    for left in range(n):
        while current_sum < m and right < n:
            current_sum += arr[right]
            right += 1
        if current_sum == m:
            count += 1
        current_sum -= arr[left]
        
    print(count)

if __name__ == "__main__":
    solve()
