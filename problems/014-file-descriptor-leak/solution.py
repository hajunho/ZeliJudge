import sys

def solve():
    """
    [ZeliJudge #014 표준 해법]
    파일 디스크립터(FD) 리소스 누수와 with 컨텍스트 매니저 시뮬레이션
    
    - NAIVE: 예외(CRASH) 발생 시 close()를 호출하지 못해 FD 영구 누수(Leak)
    - SAFE_WITH: 예외(CRASH)가 발생하더라도 __exit__()이 호출되어 FD 100% 안전 회수
    
    시간 복잡도: O(Q)
    공간 복잡도: O(Q + MAX_FD)
    """
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    max_fd = int(input_data[0])
    q = int(input_data[1])
    idx = 2

    # NAIVE 시스템 상태
    naive_open = set()
    naive_fail = 0

    # SAFE_WITH 시스템 상태
    safe_open = set()
    safe_fail = 0

    output = []

    for _ in range(q):
        cmd = input_data[idx]
        idx += 1

        if cmd == "START":
            task_id = input_data[idx]
            idx += 1

            # NAIVE 할당 시도
            if len(naive_open) < max_fd:
                naive_open.add(task_id)
            else:
                naive_fail += 1

            # SAFE 할당 시도
            if len(safe_open) < max_fd:
                safe_open.add(task_id)
            else:
                safe_fail += 1

        elif cmd == "SUCCESS":
            task_id = input_data[idx]
            idx += 1

            # 정상 종료: 둘 다 close() 성공
            naive_open.discard(task_id)
            safe_open.discard(task_id)

        elif cmd == "CRASH":
            task_id = input_data[idx]
            idx += 1

            # 비정상 종료: NAIVE는 close() 누락(누수), SAFE는 __exit__()으로 회수
            # naive_open은 그대로 유지 (Leak)
            safe_open.discard(task_id)

        elif cmd == "STATUS":
            output.append(
                f"STATUS NAIVE:[OPEN={len(naive_open)},FAIL={naive_fail}] "
                f"SAFE:[OPEN={len(safe_open)},FAIL={safe_fail}]"
            )

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == '__main__':
    solve()
