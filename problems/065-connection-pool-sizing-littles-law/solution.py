import sys
import math
from collections import deque

def get_speed(k, cores, alpha):
    if k <= 0:
        return 1.0
    if k <= cores:
        return 1.0
    factor_cpu = k / cores
    factor_cs = 1.0 + alpha * (k - cores)
    return 1.0 / (factor_cpu * factor_cs)

def simulate(pool_size, cores, alpha, requests):
    current_time = 0.0
    active_running = []
    wait_queue = deque()
    results = {}
    max_active = 0
    req_idx = 0
    n_reqs = len(requests)

    while req_idx < n_reqs or active_running or wait_queue:
        k = len(active_running)
        max_active = max(max_active, k)

        next_arrival = requests[req_idx][1] if req_idx < n_reqs else float('inf')

        if k > 0:
            speed = get_speed(k, cores, alpha)
            min_rem = min(q["rem"] for q in active_running)
            time_to_complete = min_rem / speed
            next_completion = current_time + time_to_complete
        else:
            next_completion = float('inf')

        next_event_time = min(next_arrival, next_completion)

        if next_event_time == float('inf'):
            break

        dt = next_event_time - current_time
        if dt > 1e-12 and k > 0:
            speed = get_speed(k, cores, alpha)
            work_done = dt * speed
            for q in active_running:
                q["rem"] -= work_done

        current_time = next_event_time

        # 1. Process completions
        if k > 0 and next_completion <= current_time + 1e-9:
            still_running = []
            for q in active_running:
                if q["rem"] <= 1e-9:
                    results[q["id"]] = {
                        "start": q["start"],
                        "end": current_time,
                        "latency": current_time - q["arr"]
                    }
                else:
                    still_running.append(q)
            active_running = still_running

            # Fill available slots from wait_queue
            while wait_queue and len(active_running) < pool_size:
                w_id, w_arr, w_dur = wait_queue.popleft()
                active_running.append({
                    "id": w_id,
                    "arr": w_arr,
                    "start": current_time,
                    "rem": float(w_dur)
                })

        # 2. Process arrivals
        while req_idx < n_reqs and requests[req_idx][1] <= current_time + 1e-9:
            r_id, r_arr, r_dur = requests[req_idx]
            if len(active_running) < pool_size:
                active_running.append({
                    "id": r_id,
                    "arr": r_arr,
                    "start": current_time,
                    "rem": float(r_dur)
                })
            else:
                wait_queue.append((r_id, r_arr, r_dur))
            req_idx += 1

        max_active = max(max_active, len(active_running))

    return results, max_active

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    cores = 4
    optimal_pool = 9
    oversized_pool = 50
    alpha = 0.05
    requests = []

    mode = "CONFIG"
    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "REQUESTS":
            mode = "REQUESTS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "CORES":
                cores = int(parts[1])
            elif parts[0] == "OPTIMAL_POOL_SIZE":
                optimal_pool = int(parts[1])
            elif parts[0] == "OVERSIZED_POOL_SIZE":
                oversized_pool = int(parts[1])
            elif parts[0] == "PENALTY_ALPHA":
                alpha = float(parts[1])
        elif mode == "REQUESTS":
            req_id = parts[0]
            arr = float(parts[1])
            dur = float(parts[2])
            requests.append((req_id, arr, dur))

    # Run simulations
    res_over, max_over = simulate(oversized_pool, cores, alpha, requests)
    res_opt, max_opt = simulate(optimal_pool, cores, alpha, requests)

    out_lines = []
    over_lats = []
    opt_lats = []

    for req_id, arr, dur in requests:
        o = res_over[req_id]
        p = res_opt[req_id]

        over_lats.append(o["latency"])
        opt_lats.append(p["latency"])

        out_lines.append(
            f"REQ {req_id} OVERSIZED:START={o['start']:.2f},END={o['end']:.2f},LATENCY={o['latency']:.2f} "
            f"OPTIMAL:START={p['start']:.2f},END={p['end']:.2f},LATENCY={p['latency']:.2f}"
        )

    # Summaries
    n = len(requests)
    avg_over = sum(over_lats) / n if n > 0 else 0.0
    avg_opt = sum(opt_lats) / n if n > 0 else 0.0

    sorted_over = sorted(over_lats)
    sorted_opt = sorted(opt_lats)

    p99_idx = max(0, int(math.ceil(0.99 * n)) - 1) if n > 0 else 0
    p99_over = sorted_over[p99_idx] if n > 0 else 0.0
    p99_opt = sorted_opt[p99_idx] if n > 0 else 0.0

    out_lines.append(f"SUMMARY OVERSIZED AVG_LATENCY:{avg_over:.2f} P99_LATENCY:{p99_over:.2f} MAX_CONCURRENT_RUNNING:{max_over}")
    out_lines.append(f"SUMMARY OPTIMAL AVG_LATENCY:{avg_opt:.2f} P99_LATENCY:{p99_opt:.2f} MAX_CONCURRENT_RUNNING:{max_opt}")

    ratio = (avg_over / avg_opt) if avg_opt > 0 else 1.0
    diff = avg_over - avg_opt
    out_lines.append(f"SUMMARY LATENCY_IMPROVEMENT: OPTIMAL_IS_{ratio:.2f}X_FASTER (SAVED:{diff:.2f}ms)")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
