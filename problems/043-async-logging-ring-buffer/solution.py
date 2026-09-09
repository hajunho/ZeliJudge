import sys
from collections import deque
from decimal import Decimal, ROUND_HALF_UP

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "BUFFER_CAPACITY"
    capacity = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "DISCARD_THRESHOLD_PERCENT"
    discard_percent = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "BATCH_SIZE"
    batch_size = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "EVENTS"
    events_count = int(input_data[idx + 1])
    idx += 2

    discard_limit = (capacity * discard_percent) // 100

    buffer = deque()
    total_logs = 0
    sync_disk_ops = 0
    async_batch_ops = 0
    async_written = 0
    async_dropped = 0

    out_lines = []

    for _ in range(events_count):
        cmd = input_data[idx]
        if cmd == "LOG":
            ts = input_data[idx + 1]
            level = input_data[idx + 2]
            msg_id = input_data[idx + 3]
            idx += 4

            total_logs += 1
            sync_disk_ops += 1

            remain = capacity - len(buffer)
            if remain <= discard_limit and level in ("DEBUG", "INFO"):
                async_status = "DROPPED_THRESHOLD"
                async_dropped += 1
            elif remain == 0:
                async_status = "DROPPED_FULL"
                async_dropped += 1
            else:
                async_status = "BUFFERED"
                buffer.append((level, msg_id))

            out_lines.append(
                f"LOG {ts} LEVEL:{level} MSG:{msg_id} SYNC:WRITTEN_IMMEDIATE ASYNC:{async_status} QUEUE:{len(buffer)}/{capacity}"
            )
        elif cmd == "FLUSH":
            ts = input_data[idx + 1]
            idx += 2

            pop_count = min(len(buffer), batch_size)
            if pop_count > 0:
                async_batch_ops += 1
                async_written += pop_count
                for _ in range(pop_count):
                    buffer.popleft()

            out_lines.append(
                f"FLUSH {ts} BATCH_WRITTEN:{pop_count} QUEUE:{len(buffer)}/{capacity}"
            )
        else:
            raise ValueError(f"Unknown command: {cmd}")

    if sync_disk_ops > 0:
        ratio = (Decimal(sync_disk_ops - async_batch_ops) * Decimal(100)) / Decimal(sync_disk_ops)
        io_reduction_str = str(ratio.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    else:
        io_reduction_str = "0.0"

    out_lines.append(
        f"SUMMARY TOTAL_LOGS:{total_logs} SYNC_DISK_IO_OPS:{sync_disk_ops} ASYNC_DISK_IO_OPS:{async_batch_ops} LOGS_WRITTEN:{async_written} LOGS_DROPPED:{async_dropped} IO_REDUCTION_RATE:{io_reduction_str}%"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
