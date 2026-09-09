"""
ZeliJudge Problem #010: 복사했는데 왜 둘 다 바뀌어?: 얕은 복사(Shallow Copy)와 참조의 덫
Standard Solution (Python 3)

시간 복잡도: O(N + M)
공간 복잡도: O(N)
"""
import sys

def main():
    # 고속 I/O: 전체 입력을 토큰으로 분할
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    n = int(input_data[0])
    m = int(input_data[1])
    
    # 원본 인벤토리 파싱: 2차원 리스트 [[item_id, count], ...]
    inventory = []
    idx = 2
    for _ in range(n):
        item_id = int(input_data[idx])
        count = int(input_data[idx + 1])
        inventory.append([item_id, count])
        idx += 2
        
    sim_inventory = None
    
    # 명령어 시뮬레이션
    for _ in range(m):
        cmd = input_data[idx]
        if cmd == "FORK":
            # [핵심 CS] 껍데기만 복사하는 얕은 복사(inventory.copy())를 쓰면
            # 내부 리스트 주소가 공유되어 원본이 즉시 오염됨!
            # 내부 슬롯까지 각각 새로운 메모리로 독립 복제 (Deep Clone)
            sim_inventory = [[slot[0], slot[1]] for slot in inventory]
            idx += 1
        elif cmd == "MODIFY":
            slot = int(input_data[idx + 1])
            delta = int(input_data[idx + 2])
            idx += 3
            if sim_inventory is not None:
                # 0 미만 방지 클램핑
                sim_inventory[slot][1] = max(0, sim_inventory[slot][1] + delta)
        elif cmd == "COMMIT":
            # 가상 인벤토리의 변경을 원본에 최종 반영
            if sim_inventory is not None:
                inventory = sim_inventory
                sim_inventory = None
            idx += 1
        elif cmd == "ROLLBACK":
            # 가상 세션 폐기 (원본은 전혀 오염되지 않고 유지됨)
            sim_inventory = None
            idx += 1
            
    # 최종 원본 인벤토리 상태 출력
    output_lines = [f"{slot[0]} {slot[1]}" for slot in inventory]
    print("\n".join(output_lines))

if __name__ == "__main__":
    main()
