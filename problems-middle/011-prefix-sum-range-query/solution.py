import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    q = int(input_data[1])
    
    ptr = 2
    arr = [int(x) for x in input_data[ptr:ptr+n]]
    ptr += n
    
    # 1-based 누적합 배열 생성
    prefix = [0] * (n + 1)
    for i in range(1, n + 1):
        prefix[i] = prefix[i - 1] + arr[i - 1]
        
    out = []
    for _ in range(q):
        l = int(input_data[ptr])
        r = int(input_data[ptr+1])
        ptr += 2
        out.append(str(prefix[r] - prefix[l - 1]))
        
    print("\n".join(out))

if __name__ == "__main__":
    main()
