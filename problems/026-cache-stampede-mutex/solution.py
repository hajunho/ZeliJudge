#!/usr/bin/env python3
"""
[ZeliJudge #026] 캐시가 만료된 그 1초, DB가 폭발했다: 캐시 스탬피드와 뮤텍스 방어
해답 코드: NAIVE 무방비 돌진 vs MUTEX 싱글플라이트 락 방어 엔진 O(Q)
"""
import sys
from collections import deque

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    # 1. CONFIG 파싱
    config_line = input_data[0].strip()
    config_parts = config_line.split()

    ttl_ms = 0
    cost_ms = 0
    for part in config_parts[1:]:
        k, v = part.split(":")
        if k == "TTL":
            ttl_ms = int(v)
        elif k == "QUERY_COST":
            cost_ms = int(v)

    # 2. 쿼리 개수
    q_count = int(input_data[1].strip())

    # NAIVE 상태 변수
    naive_pending = deque()  # (ready_time, valid_until)
    naive_cache_until = 0
    naive_db_count = 0

    # MUTEX 상태 변수
    mutex_cache_until = 0
    lock_busy_until = 0
    mutex_db_count = 0

    output = []

    for line in input_data[2:q_count + 2]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        t = int(parts[1])

        # A. NAIVE 엔진 처리
        while naive_pending and naive_pending[0][0] <= t:
            _, until = naive_pending.popleft()
            if until > naive_cache_until:
                naive_cache_until = until

        if t < naive_cache_until:
            naive_res = "HIT"
        else:
            naive_res = "MISS_DB_QUERY"
            naive_db_count += 1
            new_ready = t + cost_ms
            new_until = new_ready + ttl_ms
            naive_pending.append((new_ready, new_until))

        # B. MUTEX 엔진 처리
        if t < mutex_cache_until:
            mutex_res = "HIT"
        else:
            if t < lock_busy_until:
                mutex_res = "WAIT_HIT"
            else:
                mutex_res = "LOCK_DB_QUERY"
                mutex_db_count += 1
                ready = t + cost_ms
                lock_busy_until = ready
                mutex_cache_until = ready + ttl_ms

        output.append(f"REQ {t} NAIVE:{naive_res} MUTEX:{mutex_res}")

    saved = naive_db_count - mutex_db_count
    output.append(f"SUMMARY TOTAL:{q_count} NAIVE_DB:{naive_db_count} MUTEX_DB:{mutex_db_count} DB_SAVED:{saved}")

    sys.stdout.write("\n".join(output) + "\n")

if __name__ == "__main__":
    solve()
