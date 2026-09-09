#!/usr/bin/env python3
import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)
    N = int(next(it))

    committed_2pc = 0
    completed_saga = 0
    total_compensations = 0

    output_lines = []

    for _ in range(N):
        op = next(it)  # TX
        tx_id = next(it)
        order_token = next(it)
        stock_token = next(it)
        pay_token = next(it)

        s_order = order_token.split(':')[1]
        s_stock = stock_token.split(':')[1]
        s_pay = pay_token.split(':')[1]

        # 1. 2PC ?????
        if s_order == 'SUCCESS' and s_stock == 'SUCCESS' and s_pay == 'SUCCESS':
            res_2pc = "COMMITTED"
            committed_2pc += 1
        else:
            res_2pc = "ABORTED"

        # 2. SAGA ?????
        if s_order == 'FAIL':
            res_saga = "FAILED_AT:ORDER COMPENSATED:NONE"
        elif s_stock == 'FAIL':
            res_saga = "FAILED_AT:STOCK COMPENSATED:[ORDER]"
            total_compensations += 1
        elif s_pay == 'FAIL':
            res_saga = "FAILED_AT:PAYMENT COMPENSATED:[STOCK,ORDER]"
            total_compensations += 2
        else:
            res_saga = "COMPLETED"
            completed_saga += 1

        output_lines.append(f"TX {tx_id} 2PC:{res_2pc} SAGA:{res_saga}")

    output_lines.append(
        f"SUMMARY TOTAL_TX:{N} COMMITTED_2PC:{committed_2pc} COMPLETED_SAGA:{completed_saga} TOTAL_COMPENSATIONS:{total_compensations}"
    )

    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
