"""
ZeliJudge Junior Problem #040: 거품이 뽀글뽀글! 버블 정렬 시뮬레이션
Standard Solution (Python 3)
"""
import sys

def main():
    tokens = sys.stdin.read().split()
    if not tokens:
        return
    n = int(tokens[0])
    arr = [int(x) for x in tokens[1:1+n]]
    
    for i in range(n - 1):
        if arr[i] > arr[i + 1]:
            # 파이썬의 마법 스왑
            arr[i], arr[i + 1] = arr[i + 1], arr[i]
            
    print(" ".join(map(str, arr)))

if __name__ == "__main__":
    main()
