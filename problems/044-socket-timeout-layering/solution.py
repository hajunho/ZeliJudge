import sys
from decimal import Decimal, ROUND_HALF_UP

OS_SYN_TIMEOUT = 127000

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "CONNECT_TIMEOUT"
    conn_to = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "SOCKET_READ_TIMEOUT"
    read_to = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "STATEMENT_TIMEOUT"
    stmt_to = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "REQUESTS"
    requests_count = int(input_data[idx + 1])
    idx += 2

    naive_total_time = 0
    layered_total_time = 0
    out_lines = []

    for _ in range(requests_count):
        assert input_data[idx] == "REQ"
        req_id = input_data[idx + 1]
        idx += 2

        assert input_data[idx] == "CONNECT_TIME"
        t_conn = int(input_data[idx + 1])
        idx += 2

        assert input_data[idx] == "PACKETS"
        p_count = int(input_data[idx + 1])
        idx += 2

        p_gaps = []
        for _ in range(p_count):
            p_gaps.append(int(input_data[idx]))
            idx += 1

        # 1. NAIVE_STATEMENT_ONLY Simulation
        if t_conn > OS_SYN_TIMEOUT:
            naive_status = "OS_TCP_SYN_TIMEOUT"
            naive_time = OS_SYN_TIMEOUT
        else:
            stmt_elapsed = 0
            terminated = False
            for gap in p_gaps:
                stmt_elapsed += gap
                if stmt_elapsed > stmt_to:
                    naive_status = "STATEMENT_TIMEOUT"
                    naive_time = t_conn + stmt_elapsed
                    terminated = True
                    break
            if not terminated:
                naive_status = "SUCCESS"
                naive_time = t_conn + stmt_elapsed

        # 2. LAYERED_TIMEOUT Simulation
        if t_conn > conn_to:
            layered_status = "CONNECT_TIMEOUT"
            layered_time = conn_to
        else:
            stmt_elapsed = 0
            terminated = False
            for gap in p_gaps:
                if gap > read_to:
                    layered_status = "SOCKET_READ_TIMEOUT"
                    layered_time = t_conn + stmt_elapsed + read_to
                    terminated = True
                    break
                stmt_elapsed += gap
                if stmt_elapsed > stmt_to:
                    layered_status = "STATEMENT_TIMEOUT"
                    layered_time = t_conn + stmt_elapsed
                    terminated = True
                    break
            if not terminated:
                layered_status = "SUCCESS"
                layered_time = t_conn + stmt_elapsed

        time_saved = max(0, naive_time - layered_time)
        naive_total_time += naive_time
        layered_total_time += layered_time

        out_lines.append(
            f"REQ {req_id} NAIVE:{naive_status}({naive_time}ms) LAYERED:{layered_status}({layered_time}ms) TIME_SAVED:{time_saved}ms"
        )

    saved_sum = naive_total_time - layered_total_time
    if naive_total_time > 0:
        ratio = (Decimal(saved_sum) * Decimal(100)) / Decimal(naive_total_time)
        ratio_str = str(ratio.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    else:
        ratio_str = "0.0"

    out_lines.append(
        f"SUMMARY TOTAL_REQS:{requests_count} NAIVE_TOTAL_BLOCKED_TIME:{naive_total_time}ms LAYERED_TOTAL_BLOCKED_TIME:{layered_total_time}ms TOTAL_BLOCKED_TIME_SAVED:{saved_sum}ms THREAD_STARVATION_REDUCED:{ratio_str}%"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
