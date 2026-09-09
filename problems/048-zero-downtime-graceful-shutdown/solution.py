import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    idx = 0
    assert input_data[idx] == "PRESTOP_SLEEP"
    prestop_sec = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "GRACE_PERIOD"
    grace_sec = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "PROPAGATION_DELAY"
    delay_sec = int(input_data[idx + 1])
    idx += 2

    assert input_data[idx] == "EVENTS"
    events_count = int(input_data[idx + 1])
    idx += 2

    pods_term = {} # pod_id -> term_time
    total_reqs = 0
    naive_errors = 0
    graceful_errors = 0
    out_lines = []

    for _ in range(events_count):
        cmd = input_data[idx]
        if cmd == "NEW_POD":
            pod_id = input_data[idx + 1]
            idx += 2
            if pod_id not in pods_term:
                pods_term[pod_id] = None

        elif cmd == "DEPLOY_TERMINATE":
            pod_id = input_data[idx + 1]
            term_ts = int(input_data[idx + 2])
            idx += 3
            pods_term[pod_id] = term_ts

        elif cmd == "REQ":
            req_id = input_data[idx + 1]
            req_ts = int(input_data[idx + 2])
            pod_id = input_data[idx + 3]
            dur_sec = int(input_data[idx + 4])
            idx += 5

            total_reqs += 1
            t_term = pods_term.get(pod_id, None)

            # 1. NAIVE Simulation
            if t_term is None:
                naive_status = "SUCCESS"
            else:
                if req_ts + dur_sec <= t_term:
                    naive_status = "SUCCESS"
                elif req_ts < t_term and req_ts + dur_sec > t_term:
                    naive_status = "HTTP_502_DROPPED_INFLIGHT"
                else: # req_ts >= t_term
                    naive_status = "HTTP_502_ROUTED_TO_DEAD_POD"

            # 2. GRACEFUL Simulation
            if t_term is None:
                graceful_status = "SUCCESS"
            else:
                t_unroute = t_term + delay_sec
                t_sigterm = t_term + prestop_sec
                t_kill = t_sigterm + grace_sec

                if req_ts >= t_sigterm:
                    if req_ts < t_unroute:
                        graceful_status = "HTTP_502_PRESTOP_TOO_SHORT"
                    else:
                        graceful_status = "HTTP_502_ROUTED_TO_DEAD_POD"
                else: # req_ts < t_sigterm (accepted)
                    if req_ts + dur_sec <= t_kill:
                        graceful_status = "SUCCESS"
                    else:
                        graceful_status = "HTTP_502_GRACE_PERIOD_EXCEEDED"

            if naive_status != "SUCCESS":
                naive_errors += 1
            if graceful_status != "SUCCESS":
                graceful_errors += 1

            out_lines.append(
                f"REQ {req_id} AT:{req_ts} POD:{pod_id} NAIVE:{naive_status} GRACEFUL:{graceful_status}"
            )
        else:
            raise ValueError(f"Unknown command: {cmd}")

    saved = naive_errors - graceful_errors
    zero_dt = "YES" if graceful_errors == 0 else "NO"

    out_lines.append(
        f"SUMMARY TOTAL_REQS:{total_reqs} NAIVE_502_ERRORS:{naive_errors} GRACEFUL_502_ERRORS:{graceful_errors} ERRORS_SAVED:{saved} ZERO_DOWNTIME_ACHIEVED:{zero_dt}"
    )

    sys.stdout.write("\n".join(out_lines) + "\n")

if __name__ == "__main__":
    solve()
