import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    k = int(input_data[1])
    arr = [int(x) for x in input_data[2:2+n]]
    
    # 파이썬에서는 내장 정렬도 Timsort로 매우 빠름 (K번째 원소 접근)
    arr.sort()
    print(arr[k - 1])

if __name__ == "__main__":
    main()
