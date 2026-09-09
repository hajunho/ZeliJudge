import sys
from decimal import Decimal, ROUND_HALF_UP

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "NETWORK_RTT_MS"
    rtt_ms = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "FSYNC_MS"
    fsync_ms = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "BATCH_SIZE"
    batch_size = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "EVENTS"
    events_count = int(input_data[idx + 1])
    idx += 2

    current_tx_mode = "AUTOCOMMIT"
    batch_buffer = 0

    total_records = 0
    naive_total_rtt = 0
    naive_total_time = 0
    batch_total_rtt = 0
    batch_total_time = 0

    out_lines = []

    for _ in range(events_count):
        cmd = input_data[idx]
        if cmd == "TX_MODE":
            mode = input_data[idx + 1]
            idx += 2
            current_tx_mode = mode
            out_lines.append(f"TX_MODE CHANGED_TO:{mode}")

        elif cmd == "STREAM":
            count = int(input_data[idx + 1])
            idx += 2

            total_records += count
            unit_time = rtt_ms + (fsync_ms if current_tx_mode == "AUTOCOMMIT" else 0)

            # 1. NAIVE
            n_rtt = count
            n_time = count * unit_time

            # 2. BATCH
            new_total = batch_buffer + count
            flushes = new_total // batch_size
            batch_buffer = new_total % batch_size
            b_rtt = flushes
            b_time = flushes * unit_time

            naive_total_rtt += n_rtt
            naive_total_time += n_time
            batch_total_rtt += b_rtt
            batch_total_time += b_time

            out_lines.append(
                f"OP STREAM RECORDS:{count} NAIVE:RTT={n_rtt},TIME={n_time}ms BATCH:RTT={b_rtt},TIME={b_time}ms BUFFER:{batch_buffer}/{batch_size}"
            )

        elif cmd == "FLUSH":
            idx += 1
            unit_time = rtt_ms + (fsync_ms if current_tx_mode == "AUTOCOMMIT" else 0)

            flushed_cnt = batch_buffer
            if batch_buffer > 0:
                b_rtt = 1
                b_time = unit_time
                batch_buffer = 0
            else:
                b_rtt = 0
                b_time = 0

            n_rtt = 0
            n_time = 0

            batch_total_rtt += b_rtt
            batch_total_time += b_time

            out_lines.append(
                f"OP FLUSH RECORDS:{flushed_cnt} NAIVE:RTT={n_rtt},TIME={n_time}ms BATCH:RTT={b_rtt},TIME={b_time}ms BUFFER:{batch_buffer}/{batch_size}"
            )
        else:
            raise ValueError(f"Unknown command: {cmd}")

    time_saved = naive_total_time - batch_total_time

    if batch_total_time > 0:
        speedup = (Decimal(naive_total_time) / Decimal(batch_total_time)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        speedup_str = f"{speedup}x"
    else:
        speedup_str = "1.0x"

    if naive_total_rtt > 0:
        reduction = (Decimal(naive_total_rtt - batch_total_rtt) * Decimal(100) / Decimal(naive_total_rtt)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        reduction_str = f"{reduction}%"
    else:
        reduction_str = "0.0%"

    out_lines.append(
        f"SUMMARY TOTAL_RECORDS:{total_records} NAIVE_TOTAL_TIME:{naive_total_time}ms BATCH_TOTAL_TIME:{batch_total_time}ms TIME_SAVED:{time_saved}ms SPEEDUP:{speedup_str} RTT_REDUCTION_RATE:{reduction_str}"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
