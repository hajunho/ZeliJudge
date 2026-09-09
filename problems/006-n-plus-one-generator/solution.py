"""
ZeliJudge Problem #006: 쿼리 지옥과 DB 사망: N+1 문제와 스트리밍 집계
Standard Solution (Python 3)

시간 복잡도: O(N + M)
공간 복잡도: O(N + M) (해시 맵 그룹핑)
"""
import sys

def main():
    # 고속 I/O: 전체 토큰을 한 번에 파싱
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    n = int(input_data[0])
    m = int(input_data[1])
    
    # 주문 ID 목록 (N개)
    order_ids = input_data[2 : 2 + n]
    
    # [핵심 CS] N+1 반복 탐색의 O(N * M) 참사를 방지하기 위해
    # 주문상품 목록을 단 1회 선형 스캔하며 해시 맵(dict)에 그룹핑 누적: O(M)
    item_totals = {}
    
    idx = 2 + n
    for _ in range(m):
        oid = input_data[idx]
        price = int(input_data[idx + 1])
        qty = int(input_data[idx + 2])
        idx += 3
        
        item_totals[oid] = item_totals.get(oid, 0) + (price * qty)
        
    # 주문 순서대로 O(1) 해시 조회로 결과 생성 및 출력: O(N)
    output_lines = []
    for oid in order_ids:
        total = item_totals.get(oid, 0)
        output_lines.append(f"{oid} {total}")
        
    print("\n".join(output_lines))

if __name__ == "__main__":
    main()
