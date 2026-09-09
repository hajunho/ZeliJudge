"""
ZeliJudge Problem #004: 비동기의 배신과 한정판 티켓 참사: Race Condition & Mutex
Standard Solution (Python 3)

시간 복잡도:
  - 방식 A (경쟁 상태 시뮬레이션): O(N log N) (이벤트 우선순위 큐)
  - 방식 B (뮤텍스 락 시뮬레이션): O(N)
공간 복잡도: O(N)
"""
import sys
import heapq

def simulate_naive(initial_stock, transactions):
    """
    방식 A: 무방비 경쟁 상태 (Check-Then-Act 패턴)
    - T_i 시점에 잔여량 확인 (Read)
    - T_i + D_i 시점에 실제 차감 (Write)
    """
    current_stock = initial_stock
    approved_count = 0
    # min-heap for write events: (finish_time, count)
    write_heap = []
    
    for t, d, c in transactions:
        # 1. t 시점 이전에 완료된(또는 t 시점에 정확히 완료된) Write 이벤트를 먼저 반영
        while write_heap and write_heap[0][0] <= t:
            _, deduct_count = heapq.heappop(write_heap)
            current_stock -= deduct_count
            
        # 2. t 시점의 잔여량 확인 (Read)
        if current_stock >= c:
            approved_count += 1
            heapq.heappush(write_heap, (t + d, c))
            
    # 3. 모든 트랜잭션 도달 후 남아있는 차감 이벤트 일괄 반영
    while write_heap:
        _, deduct_count = heapq.heappop(write_heap)
        current_stock -= deduct_count
        
    return approved_count, current_stock

def simulate_mutex(initial_stock, transactions):
    """
    방식 B: 상호 배제 (Mutex Lock / Critical Section)
    - 오직 1개의 트랜잭션만 락을 점유
    - 락 획득 시점의 실제 최신 잔여량을 확인하여 처리
    """
    current_stock = initial_stock
    approved_count = 0
    lock_free_time = 0
    
    for t, d, c in transactions:
        # 락 획득 가능 시각 = max(도착 시각, 이전 락 해제 시각)
        start_time = max(t, lock_free_time)
        
        # 락 점유 후 최신 잔액 확인
        if current_stock >= c:
            approved_count += 1
            current_stock -= c
            lock_free_time = start_time + d
        else:
            # 잔액 부족 시 대기 없이 즉시 락 해제
            lock_free_time = start_time
            
    return approved_count, current_stock, lock_free_time

def main():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    
    s = int(input_data[0])
    n = int(input_data[1])
    
    transactions = []
    idx = 2
    for _ in range(n):
        t = int(input_data[idx])
        d = int(input_data[idx + 1])
        c = int(input_data[idx + 2])
        transactions.append((t, d, c))
        idx += 3
        
    # 방식 A 시뮬레이션
    approved_a, stock_a = simulate_naive(s, transactions)
    # 방식 B 시뮬레이션
    approved_b, stock_b, final_time_b = simulate_mutex(s, transactions)
    
    print(f"{approved_a} {stock_a}")
    print(f"{approved_b} {stock_b} {final_time_b}")

if __name__ == "__main__":
    main()
