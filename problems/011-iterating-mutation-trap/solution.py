"""
ZeliJudge Problem #011: 지웠는데 왜 건너뛰어?: 반복문 중 원소 삭제의 함정
Standard Solution (Python 3)

시간 복잡도: O(N)
공간 복잡도: O(N)
"""
import sys

def main():
    # 고속 I/O: 전체 토큰 파싱
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    n = int(input_data[0])
    words = input_data[1 : 1 + n]
    spam_word = input_data[1 + n]
    
    # [핵심 CS] 순진하게 for 루프 안에서 remove()를 호출하면
    # 1. 인덱스 시프트(Index Shift)로 인해 연속된 금지어가 건너뛰어지고
    # 2. O(N^2) 시간 복잡도로 100% 타임아웃이 발생함.
    # 해결책: 남길 원소만 단 1회 스캔(O(N))으로 수집하는 리스트 컴프리헨션
    clean_words = [w for w in words if w != spam_word]
    
    if clean_words:
        print(*(clean_words))
    else:
        print("")

if __name__ == "__main__":
    main()
