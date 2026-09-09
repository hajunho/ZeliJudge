import sys
import heapq

def simulate_pool(pool_size, timeout_ms, requests, is_naive):
    available_conns = list(range(pool_size))
    wait_queue = []
    req_map = {r['req_id']: r for r in requests}

    statuses = {}
    success_count = 0
    timeout_count = 0
    total_wait_ms = 0
    peak_active = 0

    events = []
    for r in requests:
        heapq.heappush(events, (r['timestamp'], 2, 'REQ_ARRIVE', r['req_id']))

    while events:
        t, prio, ev_type, data = heapq.heappop(events)

        if ev_type == 'CONN_RELEASE':
            conn_id = data
            available_conns.append(conn_id)

            while wait_queue and available_conns:
                waiting_id = wait_queue.pop(0)
                if statuses.get(waiting_id) == 'CONNECTION_TIMEOUT':
                    continue

                w_req = req_map[waiting_id]
                assigned_conn = available_conns.pop()
                w_t = t - w_req['timestamp']
                total_wait_ms += w_t
                statuses[waiting_id] = 'SUCCESS'
                success_count += 1

                hold = (w_req['db_ms'] + w_req['io_ms']) if is_naive else w_req['db_ms']
                heapq.heappush(events, (t + hold, 0, 'CONN_RELEASE', assigned_conn))

            active = pool_size - len(available_conns)
            if active > peak_active:
                peak_active = active

        elif ev_type == 'REQ_TIMEOUT':
            req_id = data
            if req_id not in statuses:
                statuses[req_id] = 'CONNECTION_TIMEOUT'
                timeout_count += 1

        elif ev_type == 'REQ_ARRIVE':
            req_id = data
            req = req_map[req_id]

            if available_conns:
                assigned_conn = available_conns.pop()
                statuses[req_id] = 'SUCCESS'
                success_count += 1

                hold = (req['db_ms'] + req['io_ms']) if is_naive else req['db_ms']
                heapq.heappush(events, (t + hold, 0, 'CONN_RELEASE', assigned_conn))

                active = pool_size - len(available_conns)
                if active > peak_active:
                    peak_active = active
            else:
                wait_queue.append(req_id)
                heapq.heappush(events, (t + timeout_ms, 1, 'REQ_TIMEOUT', req_id))

    avg_wait = (total_wait_ms / success_count) if success_count > 0 else 0.0
    return {
        'statuses': statuses,
        'success': success_count,
        'timeouts': timeout_count,
        'peak_active': peak_active,
        'avg_wait': avg_wait
    }

def solve():
    input_text = sys.stdin.read()
    if not input_text.strip():
        return

    lines = input_text.splitlines()
    idx = 0
    pool_size = 10
    timeout_ms = 30000

    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        if line.startswith("POOL_SIZE"):
            parts = line.split()
            if len(parts) >= 2:
                pool_size = int(parts[1])
        elif line.startswith("CONNECTION_TIMEOUT_MS"):
            parts = line.split()
            if len(parts) >= 2:
                timeout_ms = int(parts[1])
        elif line == "REQUESTS":
            break

    requests = []
    req_idx = 0
    while idx < len(lines):
        rline = lines[idx].strip()
        idx += 1
        if not rline:
            continue
        parts = rline.split()
        requests.append({
            'orig_idx': req_idx,
            'req_id': parts[0],
            'type': parts[1],
            'db_ms': int(parts[2]),
            'io_ms': int(parts[3]),
            'timestamp': int(parts[4])
        })
        req_idx += 1

    # Sort requests chronologically, stable tie-break by orig_idx
    requests.sort(key=lambda x: (x['timestamp'], x['orig_idx']))

    naive_res = simulate_pool(pool_size, timeout_ms, requests, is_naive=True)
    opt_res = simulate_pool(pool_size, timeout_ms, requests, is_naive=False)

    for req in requests:
        rid = req['req_id']
        n_st = naive_res['statuses'].get(rid, 'CONNECTION_TIMEOUT')
        o_st = opt_res['statuses'].get(rid, 'CONNECTION_TIMEOUT')
        sys.stdout.write(f"REQ {rid} NAIVE:{n_st} OPTIMIZED:{o_st}\n")

    sys.stdout.write(f"SUMMARY NAIVE SUCCESS:{naive_res['success']} TIMEOUTS:{naive_res['timeouts']} PEAK_CONNS:{naive_res['peak_active']} AVG_WAIT_MS:{naive_res['avg_wait']:.1f}\n")
    sys.stdout.write(f"SUMMARY OPTIMIZED SUCCESS:{opt_res['success']} TIMEOUTS:{opt_res['timeouts']} PEAK_CONNS:{opt_res['peak_active']} AVG_WAIT_MS:{opt_res['avg_wait']:.1f}\n")
    sys.stdout.write(f"SUMMARY TIMEOUTS_PREVENTED:{naive_res['timeouts'] - opt_res['timeouts']}\n")

if __name__ == '__main__':
    solve()
