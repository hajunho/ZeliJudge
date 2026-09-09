"""
ZeliJudge Junior Problem #049: 가장 작은 것부터 맨 앞으로! 선택 정렬 1회전
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    arr = [int(x) for x in tokens[1:1+n]]
    
    # 최솟값의 인덱스 찾기
    min_idx = 0
    for i in range(1, n):
        if arr[i] < arr[min_idx]:
            min_idx = i
            
    # 0번 인덱스와 스왑
    arr[0], arr[min_idx] = arr[min_idx], arr[0]
    
    print(" ".join(map(str, arr)))

if __name__ == "__main__":
    main()
