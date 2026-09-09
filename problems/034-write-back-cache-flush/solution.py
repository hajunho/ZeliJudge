#!/usr/bin/env python3
import sys
from collections import defaultdict

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)

    cmd = next(it)  # CONFIG
    b_token = next(it)
    i_token = next(it)

    B = int(b_token.split(':')[1])
    interval_ms = int(i_token.split(':')[1])

    N = int(next(it))

    wt_queries = 0
    wb_queries = 0

    wb_cache = defaultdict(int)
    dirty_buffer = defaultdict(int)
    dirty_event_count = 0
    last_flush_time = 0
    last_event_time = 0

    def do_flush(flush_type, current_t):
        nonlocal wb_queries, dirty_event_count, last_flush_time
        if dirty_event_count > 0:
            k_cnt = len(dirty_buffer)
            sum_delta = sum(dirty_buffer.values())
            wb_queries += 1
            print(f"[FLUSH:{flush_type}] t:{current_t} DIRTY_KEYS:{k_cnt} TOTAL_DELTA:{sum_delta}")
            dirty_buffer.clear()
            dirty_event_count = 0
            last_flush_time = current_t

    for _ in range(N):
        op = next(it)
        if op == "INCREMENT":
            t = int(next(it))
            key = next(it)
            delta = int(next(it))
            last_event_time = t

            if dirty_event_count > 0 and t >= last_flush_time + interval_ms:
                do_flush("TIME", t)

            wt_queries += 1
            wb_cache[key] += delta
            dirty_buffer[key] += delta
            dirty_event_count += 1

            if dirty_event_count == B:
                do_flush("BATCH", t)

        elif op == "READ":
            t = int(next(it))
            key = next(it)
            last_event_time = t

            if dirty_event_count > 0 and t >= last_flush_time + interval_ms:
                do_flush("TIME", t)

            val = wb_cache[key]
            print(f"READ {key} VALUE:{val}")

        elif op == "FORCE_FLUSH":
            t = int(next(it))
            last_event_time = t

            if dirty_event_count > 0 and t >= last_flush_time + interval_ms:
                do_flush("TIME", t)
            elif dirty_event_count > 0:
                do_flush("FORCE", t)

    # ?? ???
    if dirty_event_count > 0:
        do_flush("FINAL", last_event_time)

    saved = wt_queries - wb_queries
    if wt_queries > 0:
        rate = f"{(saved / wt_queries * 100):.1f}%"
    else:
        rate = "0.0%"

    print(
        f"SUMMARY TOTAL_EVENTS:{N} WT_DB_QUERIES:{wt_queries} WB_DB_QUERIES:{wb_queries} QUERIES_SAVED:{saved} REDUCTION_RATE:{rate}"
    )

if __name__ == '__main__':
    solve()
