#!/usr/bin/env python3
"""
[ZeliJudge #024] 새로고침 5번 눌렀더니 결제가 5번 됐어요?!: 멱등성과 멱등키의 방패
해답 코드: NAIVE 무차별 결제 vs 멱등키 기반 캐시 재생 엔진 O(Q)
"""
import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    # 1. 초기 잔액 파싱
    first_parts = input_data[0].strip().split()
    initial_balance = int(first_parts[1])

    # 2. 쿼리 개수
    q_count = int(input_data[1].strip())

    naive_bal = initial_balance
    idempotent_bal = initial_balance
    cache = {}  # key -> result ("CHARGED" or "INSUFFICIENT")

    output = []

    for line in input_data[2:q_count + 2]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        # REQ <idempotency_key> <amount>
        key = parts[1]
        amount = int(parts[2])

        # A. NAIVE 엔진
        if naive_bal >= amount:
            naive_bal -= amount
            naive_res = "CHARGED"
        else:
            naive_res = "INSUFFICIENT"

        # B. IDEMPOTENT 엔진
        if key == "-":
            # 멱등키 없는 레거시 요청
            if idempotent_bal >= amount:
                idempotent_bal -= amount
                idemp_res = "NO_KEY:CHARGED"
            else:
                idemp_res = "NO_KEY:INSUFFICIENT"
        else:
            if key in cache:
                # 중복 재시도 -> 실제 결제 없이 이전 응답 재생
                cached_res = cache[key]
                idemp_res = f"CACHED_REPLAY:{cached_res}"
            else:
                # 최초 실행
                if idempotent_bal >= amount:
                    idempotent_bal -= amount
                    status = "CHARGED"
                else:
                    status = "INSUFFICIENT"
                cache[key] = status
                idemp_res = f"FIRST_RUN:{status}"

        output.append(f"TX NAIVE:{naive_res} IDEMPOTENT:{idemp_res}")

    diff = idempotent_bal - naive_bal
    output.append(f"SUMMARY NAIVE_BAL:{naive_bal} IDEMPOTENT_BAL:{idempotent_bal} DIFF:{diff}")

    sys.stdout.write("\n".join(output) + "\n")

if __name__ == "__main__":
    solve()
