"""
ZeliJudge Problem #005: 문자열 덧셈의 늪: 불변 객체(Immutable)와 메모리 복사 지옥
Standard Solution (Python 3)

시간 복잡도: O(Total Characters) = O(N)
공간 복잡도: O(N) (가변 버퍼 리스트 및 단 1회 메모리 할당)
"""
import sys

def main():
    # 고속 I/O: 개행을 기준으로 모든 로그 라인을 분할
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    
    n = int(lines[0])
    
    # [핵심 CS] 불변 문자열 누적(+=)의 O(N^2) 메모리 복사 참사를 피하기 위해
    # 가변 리스트(Mutable List)를 버퍼로 활용하여 O(1)로 수집
    prefix = "[ERROR] "
    prefix_len = len(prefix)
    
    error_messages = []
    for line in lines[1 : 1 + n]:
        if line.startswith(prefix):
            error_messages.append(line[prefix_len:])
            
    if not error_messages:
        print("")
        return
    
    # CPython C-레벨에서 단 1번의 메모리 할당으로 O(N) 고속 결합
    print("\n".join(error_messages))

if __name__ == "__main__":
    main()
