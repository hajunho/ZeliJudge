import sys

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n, s = map(int, lines[0].split())
    arr = [int(x) for x in lines[1].split()]
    
    count = 0
    curr_sum = 0
    left = 0
    
    for right in range(n):
        curr_sum += arr[right]
        
        while curr_sum > s and left <= right:
            curr_sum -= arr[left]
            left += 1
            
        if curr_sum == s:
            count += 1
            
    print(count)

if __name__ == "__main__":
    main()
