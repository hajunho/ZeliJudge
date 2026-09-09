import sys
import heapq
from collections import defaultdict

def pseudo_rand(client_id, attempt, limit):
    s = sum((i + 1) * ord(c) for i, c in enumerate(client_id))
    val = (s * 31337 + attempt * 7919) % (limit + 1)
    return val

def run_simulation(strategy, raw_requests, capacity, down_start, down_end, max_attempts, base_delay, cap_delay):
    # heap elements: (timestamp, seq, client_id, attempt)
    heap = []
    seq = 0
    for t, client_id in raw_requests:
        seq += 1
        heapq.heappush(heap, (t, seq, client_id, 1))

    processed_count = defaultdict(int)
    # client_id -> {'status': 'FAIL', 'attempts': 1}
    results = {}
    for _, client_id in raw_requests:
        results[client_id] = {'status': 'FAIL', 'attempts': 1}

    total_attempts_executed = 0

    while heap:
        t, _, client_id, attempt = heapq.heappop(heap)
        total_attempts_executed += 1
        results[client_id]['attempts'] = attempt

        # Check server availability at time t
        is_down = (down_start <= t < down_end)
        if not is_down and processed_count[t] < capacity:
            processed_count[t] += 1
            results[client_id]['status'] = 'SUCCESS'
            continue

        # Failed (either is_down or overload)
        if attempt < max_attempts:
            if strategy == 'IMMEDIATE':
                next_t = t
            elif strategy == 'FIXED':
                next_t = t + base_delay
            elif strategy == 'FULL_JITTER':
                temp = min(cap_delay, base_delay * (2 ** (attempt - 1)))
                jitter = pseudo_rand(client_id, attempt, temp)
                next_t = t + max(1, jitter)

            seq += 1
            heapq.heappush(heap, (next_t, seq, client_id, attempt + 1))
        else:
            results[client_id]['status'] = 'FAIL'

    return results, total_attempts_executed

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    capacity = 5
    down_start = 10
    down_end = 20
    max_attempts = 4
    base_delay = 1
    cap_delay = 8

    idx = 0
    while idx < len(input_data):
        line = input_data[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "SERVER_CAPACITY":
            capacity = int(parts[1])
        elif parts[0] == "SERVER_DOWN_WINDOW":
            down_start = int(parts[1])
            down_end = int(parts[2])
        elif parts[0] == "MAX_ATTEMPTS":
            max_attempts = int(parts[1])
        elif parts[0] == "BASE_DELAY_SEC":
            base_delay = int(parts[1])
        elif parts[0] == "CAP_DELAY_SEC":
            cap_delay = int(parts[1])
        elif parts[0] == "EVENTS":
            break

    raw_requests = []
    while idx < len(input_data):
        line = input_data[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "REQ":
            client_id = parts[1]
            t = int(parts[2])
            raw_requests.append((t, client_id))

    total_reqs = len(raw_requests)

    # Run simulations for all 3 strategies
    imm_res, imm_total_att = run_simulation('IMMEDIATE', raw_requests, capacity, down_start, down_end, max_attempts, base_delay, cap_delay)
    fix_res, fix_total_att = run_simulation('FIXED', raw_requests, capacity, down_start, down_end, max_attempts, base_delay, cap_delay)
    jit_res, jit_total_att = run_simulation('FULL_JITTER', raw_requests, capacity, down_start, down_end, max_attempts, base_delay, cap_delay)

    imm_succ = 0
    fix_succ = 0
    jit_succ = 0

    for t, client_id in raw_requests:
        i_st, i_at = imm_res[client_id]['status'], imm_res[client_id]['attempts']
        f_st, f_at = fix_res[client_id]['status'], fix_res[client_id]['attempts']
        j_st, j_at = jit_res[client_id]['status'], jit_res[client_id]['attempts']

        if i_st == 'SUCCESS':
            imm_succ += 1
        if f_st == 'SUCCESS':
            fix_succ += 1
        if j_st == 'SUCCESS':
            jit_succ += 1

        print(f"REQ {client_id} AT:{t} IMMEDIATE:{i_st},ATTEMPTS:{i_at} FIXED:{f_st},ATTEMPTS:{f_at} JITTER:{j_st},ATTEMPTS:{j_at}")

    imm_rate = (imm_succ / total_reqs * 100.0) if total_reqs > 0 else 0.0
    fix_rate = (fix_succ / total_reqs * 100.0) if total_reqs > 0 else 0.0
    jit_rate = (jit_succ / total_reqs * 100.0) if total_reqs > 0 else 0.0

    advantage = jit_rate - fix_rate

    print(f"SUMMARY IMMEDIATE SUCCESS_RATE:{imm_rate:.2f}% TOTAL_ATTEMPTS:{imm_total_att}")
    print(f"SUMMARY FIXED SUCCESS_RATE:{fix_rate:.2f}% TOTAL_ATTEMPTS:{fix_total_att}")
    print(f"SUMMARY FULL_JITTER SUCCESS_RATE:{jit_rate:.2f}% TOTAL_ATTEMPTS:{jit_total_att}")
    print(f"SUMMARY JITTER_RELIABILITY_ADVANTAGE:{advantage:.2f}%")

if __name__ == "__main__":
    solve()
