import sys
from decimal import Decimal, ROUND_HALF_UP

class Subtask:
    __slots__ = ('name', 'duration', 'status')
    def __init__(self, name, duration, status):
        self.name = name
        self.duration = duration
        self.status = status

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "GLOBAL_TIMEOUT"
    timeout_ms = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "PARTIAL_FAILURE_POLICY"
    policy = input_data[idx + 1]
    idx += 2

    assert input_data[idx] == "REQUESTS"
    requests_count = int(input_data[idx + 1])
    idx += 2

    sum_serial = 0
    sum_parallel = 0
    sum_saved = 0
    out_lines = []

    for _ in range(requests_count):
        assert input_data[idx] == "REQ"
        req_id = input_data[idx + 1]
        idx += 2

        assert input_data[idx] == "SUBTASKS"
        k_tasks = int(input_data[idx + 1])
        idx += 2

        tasks = []
        for _ in range(k_tasks):
            assert input_data[idx] == "SUBTASK"
            t_name = input_data[idx + 1]
            idx += 2

            assert input_data[idx] == "DURATION"
            t_dur = int(input_data[idx + 1])
            idx += 2

            assert input_data[idx] == "STATUS"
            t_stat = input_data[idx + 1]
            idx += 2

            tasks.append(Subtask(t_name, t_dur, t_stat))

        # 1. SERIAL_SYNC Simulation
        s_elapsed = 0
        s_status = "SUCCESS"
        s_time = 0
        has_error = False

        for t in tasks:
            if s_elapsed + t.duration > timeout_ms:
                s_status = "TIMEOUT"
                s_time = timeout_ms
                break
            s_elapsed += t.duration
            if t.status == "ERROR":
                has_error = True
                if policy == "FAIL_FAST":
                    s_status = "FAILED"
                    s_time = s_elapsed
                    break
        
        if s_status not in ("TIMEOUT", "FAILED"):
            s_time = s_elapsed
            if policy == "ALL_SETTLED" and has_error:
                if all(t.status == "ERROR" for t in tasks):
                    s_status = "FAILED"
                else:
                    s_status = "DEGRADED_SUCCESS"
            else:
                s_status = "SUCCESS"

        # 2. PARALLEL_ASYNC Simulation
        p_status = "SUCCESS"
        p_time = 0

        if not tasks:
            p_status = "SUCCESS"
            p_time = 0
        elif policy == "FAIL_FAST":
            # Find earliest failure event
            failures = []
            for t in tasks:
                if t.duration > timeout_ms:
                    failures.append((timeout_ms, "TIMEOUT"))
                elif t.status == "ERROR":
                    failures.append((t.duration, "FAILED"))
            
            if failures:
                # Sort by time, pick earliest failure
                failures.sort(key=lambda x: x[0])
                first_time, first_type = failures[0]
                p_status = first_type
                p_time = first_time
            else:
                p_status = "SUCCESS"
                p_time = max(t.duration for t in tasks)
        else: # ALL_SETTLED
            p_time = min(timeout_ms, max(t.duration for t in tasks))
            ok_cnt = sum(1 for t in tasks if t.duration <= timeout_ms and t.status == "OK")
            err_cnt = sum(1 for t in tasks if t.duration <= timeout_ms and t.status == "ERROR")
            to_cnt = sum(1 for t in tasks if t.duration > timeout_ms)

            if ok_cnt == len(tasks):
                p_status = "SUCCESS"
            elif ok_cnt > 0:
                p_status = "DEGRADED_SUCCESS"
            else:
                if err_cnt > 0:
                    p_status = "FAILED"
                else:
                    p_status = "TIMEOUT"

        latency_diff = max(0, s_time - p_time)
        sum_serial += s_time
        sum_parallel += p_time
        sum_saved += latency_diff

        out_lines.append(
            f"REQ {req_id} SERIAL:{s_status}({s_time}ms) PARALLEL:{p_status}({p_time}ms) LATENCY_IMPROVEMENT:{latency_diff}ms"
        )

    if sum_parallel > 0:
        ratio = (Decimal(sum_serial) / Decimal(sum_parallel)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        speedup_str = f"{ratio}x"
    else:
        speedup_str = "1.0x"

    out_lines.append(
        f"SUMMARY TOTAL_REQS:{requests_count} SERIAL_TOTAL_TIME:{sum_serial}ms PARALLEL_TOTAL_TIME:{sum_parallel}ms TOTAL_LATENCY_SAVED:{sum_saved}ms AVG_SPEEDUP:{speedup_str}"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
