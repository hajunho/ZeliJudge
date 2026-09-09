import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    nums = [int(x) for x in tokens[1:1+n]]
    
    if n == 0:
        print(0)
        return
        
    max_len = 1
    curr_len = 1
    
    for i in range(1, n):
        if nums[i] > nums[i - 1]:
            curr_len += 1
            if curr_len > max_len:
                max_len = curr_len
        else:
            curr_len = 1
            
    print(max_len)

if __name__ == "__main__":
    main()
