import sys
import math

def main():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    n = int(lines[0].strip())
    nums = [int(x) for x in lines[1].split()]
    
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            if math.gcd(nums[i], nums[j]) == 1:
                count += 1
                
    print(count)

if __name__ == "__main__":
    main()
