"""
ZeliJudge Problem #007: 정렬의 배신과 최악의 분할: 퀵소트 O(N²) 함정과 Timsort
Standard Solution (Python 3)

시간 복잡도: O(N log N) (Timsort 활용 - 이미 정렬된 경우 O(N) 최선 보장)
공간 복잡도: O(N)
"""
import sys

def main():
    # 고속 I/O: 전체 토큰을 한 번에 파싱
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    n = int(input_data[0])
    arr = [int(x) for x in input_data[1 : 1 + n]]
    
    # [핵심 CS] 첫 번째 원소를 피벗으로 잡는 나이브 퀵소트는
    # 정렬된 배열, 역순 배열, 동일 원소 배열에서 O(N^2)로 추락하지만,
    # 파이썬 내장 Timsort는 최선의 경우 O(N), 최악의 경우에도 O(N log N)을 엄격히 보장
    arr.sort()
    
    # 결과 고속 출력
    print(*(arr))

if __name__ == "__main__":
    main()
