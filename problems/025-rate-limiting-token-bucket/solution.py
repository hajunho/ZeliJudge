#!/usr/bin/env python3
"""
[ZeliJudge #025] 1초에 1,000명이 몰려왔다!: 처리율 제한 장치와 토큰 버킷
해답 코드: 지연 평가(Lazy Refill) 기반 토큰 버킷 알고리즘 O(Q)
"""
import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    # 1. CONFIG 파싱
    config_line = input_data[0].strip()
    config_parts = config_line.split()

    cap = 0
    refill_ms = 0
    for part in config_parts[1:]:
        k, v = part.split(":")
        if k == "CAPACITY":
            cap = int(v)
        elif k == "REFILL_MS":
            refill_ms = int(v)

    # 2. 쿼리 개수
    q_count = int(input_data[1].strip())

    tokens = cap
    t_last = 0
    allowed_cnt = 0
    throttled_cnt = 0

    output = []

    for line in input_data[2:q_count + 2]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        t = int(parts[1])

        # A. 지연 평가 토큰 충전
        delta_t = t - t_last
        add_tokens = delta_t // refill_ms
        tokens = min(cap, tokens + add_tokens)

        if tokens == cap:
            t_last = t
        else:
            t_last += add_tokens * refill_ms

        # B. 토큰 소비 및 허용/차단 판정
        if tokens >= 1:
            tokens -= 1
            allowed_cnt += 1
            output.append(f"REQ {t} ALLOWED REMAINING:{tokens}")
        else:
            throttled_cnt += 1
            next_wait = refill_ms - (t - t_last)
            output.append(f"REQ {t} THROTTLED RETRY_AFTER:{next_wait}ms")

    output.append(f"SUMMARY TOTAL:{q_count} ALLOWED:{allowed_cnt} THROTTLED:{throttled_cnt}")
    sys.stdout.write("\n".join(output) + "\n")

if __name__ == "__main__":
    solve()
