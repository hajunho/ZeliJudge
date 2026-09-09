"""
ZeliJudge Problem #009: 캐시의 배신과 메모리 누수: LRU 캐시의 마법
Standard Solution (Python 3)

시간 복잡도: GET O(1), PUT O(1)
공간 복잡도: O(C) (최대 용량 C 유지)
"""
import sys
from collections import OrderedDict

def main():
    # 고속 I/O: 전체 명령어를 토큰 단위로 한 번에 파싱
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    c = int(input_data[0])
    q = int(input_data[1])
    
    # [핵심 CS] 해시 맵 + 이중 연결 리스트가 C-레벨로 결합된 OrderedDict를 활용
    # 모든 탐색, 삽입, 위치 이동, 축출(Evict) 연산을 평균 O(1)에 보장
    cache = OrderedDict()
    output_lines = []
    
    idx = 2
    for _ in range(q):
        cmd = input_data[idx]
        if cmd == "PUT":
            key = input_data[idx + 1]
            val = input_data[idx + 2]
            idx += 3
            
            if key in cache:
                cache.move_to_end(key)
            cache[key] = val
            
            # 용량 초과 시 가장 오랫동안 사용되지 않은(맨 앞) 원소를 O(1) 축출
            if len(cache) > c:
                cache.popitem(last=False)
                
        elif cmd == "GET":
            key = input_data[idx + 1]
            idx += 2
            
            if key in cache:
                # 캐시 적중(Hit) 시 가장 최근 사용(MRU, 맨 뒤)으로 O(1) 승격
                cache.move_to_end(key)
                output_lines.append(cache[key])
            else:
                # 캐시 미스(Miss)
                output_lines.append("-1")
                
    # 버퍼 모아서 단 1회 출력
    print("\n".join(output_lines))

if __name__ == "__main__":
    main()
