import sys

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    arr = [int(x) for x in input_data[1:1+n]]
    
    # 1. 중복 제거 후 정렬
    sorted_unique = sorted(set(arr))
    
    # 2. 값 -> 순위 매핑 딕셔너리
    rank_map = {val: idx for idx, val in enumerate(sorted_unique)}
    
    # 3. 원본 배열 순위 변환
    compressed = [str(rank_map[x]) for x in arr]
    print(" ".join(compressed))

if __name__ == "__main__":
    main()
