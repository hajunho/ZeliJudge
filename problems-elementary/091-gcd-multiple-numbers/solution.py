import sys

def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a

def main():
    parts = sys.stdin.read().split()
    if not parts:
        return
    n = int(parts[0])
    nums = [int(x) for x in parts[1:1+n]]
    
    current_gcd = nums[0]
    for x in nums[1:]:
        current_gcd = gcd(current_gcd, x)
        
    print(current_gcd)

if __name__ == "__main__":
    main()
