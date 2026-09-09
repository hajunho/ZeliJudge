import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    nums = [int(x) for x in input_data[1:1+n]]
    
    # 0부터 1000까지 카운트 배열
    count = [0] * 1001
    for num in nums:
        count[num] += 1
        
    result = []
    for val in range(1001):
        if count[val] > 0:
            result.extend([str(val)] * count[val])
            
    print(" ".join(result))

if __name__ == "__main__":
    main()
