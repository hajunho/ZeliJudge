"""
ZeliJudge Problem #001: 10만 건 데이터 참사: O(N²)의 늪과 해시 검색
Standard Solution (Python 3)

시간 복잡도: O(N + M + K log K)  (K <= min(N, M))
공간 복잡도: O(N + M)
"""
import sys

def main():
    # 고속 I/O: 대용량 데이터(20만 개 이상 토큰)를 한 번에 읽기
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    n = int(input_data[0])
    m = int(input_data[1])
    
    # 토큰 슬라이싱
    a_tokens = input_data[2 : 2 + n]
    b_tokens = input_data[2 + n : 2 + n + m]
    
    # 정수 변환 및 집합(해시셋) 생성: O(N + M)
    set_a = set(map(int, a_tokens))
    set_b = set(map(int, b_tokens))
    
    # C-레벨 초고속 해시 교집합: O(min(N, M))
    common = set_a & set_b
    
    if not common:
        print("")
        return
    
    # 오름차순 정렬: O(K log K)
    result = sorted(common)
    
    # 표준 출력
    print(*(result))

if __name__ == "__main__":
    main()
