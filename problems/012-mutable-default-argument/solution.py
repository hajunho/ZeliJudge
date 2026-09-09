import sys

def solve():
    """
    [ZeliJudge #012 표준 해법]
    가변 기본 인자(Mutable Default Argument)의 저주 시뮬레이션
    
    - Buggy 시스템: 함수 정의 시점에 생성된 단 하나의 공용 리스트(buggy_default_cart)를
                   DEFAULT 모드의 모든 유저가 공유(Same Reference)함.
    - Fixed 시스템: None Sentinel 패턴을 사용하여 DEFAULT 모드이든 PRIVATE 모드이든
                   호출 시점에 매번 새로운 빈 리스트([])를 생성하여 독립성을 보장함.
    
    시간 복잡도: O(Q)
    공간 복잡도: O(Q + U)
    """
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    q = int(input_data[0])
    idx = 1
    
    # Buggy 시스템: 정의 시점 단 1회 생성된 공용 기본 객체
    buggy_default_cart = []
    buggy_carts = {}
    
    # Fixed 시스템: 유저별 독립 카트
    fixed_carts = {}
    
    output = []
    
    for _ in range(q):
        cmd = input_data[idx]
        idx += 1
        
        if cmd == "OPEN":
            user = input_data[idx]
            mode = input_data[idx + 1]
            idx += 2
            
            if mode == "DEFAULT":
                buggy_carts[user] = buggy_default_cart
                fixed_carts[user] = []
            else:  # PRIVATE
                buggy_carts[user] = []
                fixed_carts[user] = []
                
        elif cmd == "ADD":
            user = input_data[idx]
            item = input_data[idx + 1]
            idx += 2
            
            buggy_carts[user].append(item)
            fixed_carts[user].append(item)
            
        elif cmd == "COUNT":
            user = input_data[idx]
            idx += 1
            
            b_cnt = len(buggy_carts[user])
            f_cnt = len(fixed_carts[user])
            output.append(f"{user} BUGGY:{b_cnt} FIXED:{f_cnt}")
            
        elif cmd == "CHECK_SAME":
            user1 = input_data[idx]
            user2 = input_data[idx + 1]
            idx += 2
            
            b_same = "YES" if (buggy_carts[user1] is buggy_carts[user2]) else "NO"
            f_same = "YES" if (fixed_carts[user1] is fixed_carts[user2]) else "NO"
            output.append(f"SAME_REF BUGGY:{b_same} FIXED:{f_same}")
            
    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
