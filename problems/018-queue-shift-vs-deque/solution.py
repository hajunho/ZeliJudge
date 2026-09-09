import sys
from collections import deque

def solve():
    """
    [ZeliJudge #018 표준 해법]
    FIFO 큐에서 list.pop(0)의 O(N) 시프트 비용 계측과 collections.deque 최적화
    
    - NAIVE_LIST: pop(0) 마다 (남은 원소 수 - 1) 번의 메모리 시프트 발생 -> O(N^2)
    - OPTIMIZED_DEQUE: popleft()는 포인터 조작만으로 O(1) 처리
    
    시간 복잡도: O(Q)
    공간 복잡도: O(Q)
    """
    tokens = sys.stdin.read().split()
    if not tokens:
        return

    q_count = int(tokens[0])
    idx = 1

    # 최적화된 deque로 O(1) 큐 관리
    q = deque()
    total_shifts = 0
    output = []

    for _ in range(q_count):
        cmd = tokens[idx]
        idx += 1

        if cmd == "ENQUEUE":
            user_id = tokens[idx]
            idx += 1
            q.append(user_id)

        elif cmd == "DEQUEUE":
            if q:
                # NAIVE_LIST 기준: 맨 앞 제거 시 뒤따르는 (len - 1)개 원소가 시프트됨
                total_shifts += len(q) - 1
                q.popleft()

        elif cmd == "STATUS":
            output.append(f"STATUS QUEUE_LEN:{len(q)} TOTAL_SHIFTS:{total_shifts}")

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
