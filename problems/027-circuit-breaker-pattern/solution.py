#!/usr/bin/env python3
"""
[ZeliJudge #027] 옆 동네 서버가 터졌는데 우리 서버까지 죽어요?: 서킷 브레이커와 장애 격리
해답 코드: 서킷 브레이커 유한 상태 머신(FSM) 시뮬레이션 O(Q)
"""
import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    # 1. CONFIG 파싱
    config_line = input_data[0].strip()
    config_parts = config_line.split()

    fail_threshold = 0
    recovery_timeout = 0
    success_threshold = 0

    for part in config_parts[1:]:
        k, v = part.split(":")
        if k == "FAILURE_THRESHOLD":
            fail_threshold = int(v)
        elif k == "RECOVERY_TIMEOUT":
            recovery_timeout = int(v)
        elif k == "SUCCESS_THRESHOLD":
            success_threshold = int(v)

    # 2. 쿼리 개수
    q_count = int(input_data[1].strip())

    state = "CLOSED"
    consecutive_fails = 0
    consecutive_successes = 0
    open_time = -1

    passed_cnt = 0
    blocked_cnt = 0
    state_changes = 0

    output = []

    for line in input_data[2:q_count + 2]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        t = int(parts[1])
        call_result = parts[2]

        # 단계 1: 냉각 시간 만료 검사
        if state == "OPEN" and t >= open_time + recovery_timeout:
            state = "HALF_OPEN"
            consecutive_successes = 0
            state_changes += 1

        curr_state = state

        # 단계 2: 현재 상태별 액션 수행
        if state == "OPEN":
            action = "FAST_FAIL"
            blocked_cnt += 1

        elif state == "HALF_OPEN":
            passed_cnt += 1
            if call_result == "SUCCESS":
                action = "HALF_OPEN_CALL:SUCCESS"
                consecutive_successes += 1
                if consecutive_successes >= success_threshold:
                    state = "CLOSED"
                    consecutive_fails = 0
                    state_changes += 1
            else:
                action = "HALF_OPEN_CALL:FAIL"
                state = "OPEN"
                open_time = t
                state_changes += 1

        elif state == "CLOSED":
            passed_cnt += 1
            if call_result == "SUCCESS":
                action = "PASSTHROUGH:SUCCESS"
                consecutive_fails = 0
            else:
                action = "PASSTHROUGH:FAIL"
                consecutive_fails += 1
                if consecutive_fails >= fail_threshold:
                    state = "OPEN"
                    open_time = t
                    state_changes += 1

        output.append(f"REQ {t} STATE:{curr_state} ACTION:{action}")

    output.append(f"SUMMARY TOTAL:{q_count} PASSED:{passed_cnt} BLOCKED:{blocked_cnt} STATE_CHANGES:{state_changes}")
    sys.stdout.write("\n".join(output) + "\n")

if __name__ == "__main__":
    solve()
