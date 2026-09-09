import sys
import heapq

def solve():
    input_text = sys.stdin.read()
    if not input_text.strip():
        return

    lines = input_text.splitlines()
    idx = 0
    ttl_ms = 86400000
    balances = {}

    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        if line.startswith("IDEMPOTENCY_TTL_MS"):
            parts = line.split()
            if len(parts) >= 2:
                ttl_ms = int(parts[1])
        elif line == "BALANCES":
            while idx < len(lines):
                bline = lines[idx].strip()
                if not bline or bline == "REQUESTS":
                    break
                idx += 1
                parts = bline.split()
                balances[parts[0]] = int(parts[1])
        elif line == "REQUESTS":
            break

    raw_requests = []
    req_idx = 0
    while idx < len(lines):
        rline = lines[idx].strip()
        idx += 1
        if not rline:
            continue
        parts = rline.split()
        raw_requests.append({
            'orig_idx': req_idx,
            'req_id': parts[0],
            'user_id': parts[1],
            'amount': int(parts[2]),
            'idempotency_key': parts[3],
            'timestamp': int(parts[4]),
            'duration_ms': int(parts[5]) if len(parts) >= 6 else 50
        })
        req_idx += 1

    # Sort requests by timestamp ascending; stable tie-break by orig_idx
    raw_requests.sort(key=lambda x: (x['timestamp'], x['orig_idx']))

    # --- NAIVE MODEL ---
    naive_balances = dict(balances)
    naive_success = 0
    naive_fail = 0
    naive_dup = 0
    naive_overcharged = 0
    naive_charged_keys = {}
    naive_statuses = {}

    for req in raw_requests:
        rid = req['req_id']
        u = req['user_id']
        amt = req['amount']
        k = req['idempotency_key']
        t = req['timestamp']
        dur = req['duration_ms']

        bal = naive_balances.get(u, 0)
        if bal >= amt:
            naive_balances[u] = bal - amt
            status = "SUCCESS"
            naive_success += 1

            if k != "NONE":
                kt = (u, k)
                if kt in naive_charged_keys and t <= naive_charged_keys[kt]:
                    naive_dup += 1
                    naive_overcharged += amt
                else:
                    naive_charged_keys[kt] = t + dur + ttl_ms
        else:
            status = "INSUFFICIENT_FUNDS"
            naive_fail += 1

        naive_statuses[rid] = status

    # --- IDEMPOTENT MODEL ---
    idem_balances = dict(balances)
    idem_success = 0
    idem_fail = 0
    cached_resp = 0
    conflict_in_flight = 0
    mismatches = 0

    in_flight = {}
    in_flight_heap = []
    completed_cache = {}
    idem_statuses = {}

    for req in raw_requests:
        rid = req['req_id']
        u = req['user_id']
        amt = req['amount']
        k = req['idempotency_key']
        t = req['timestamp']
        dur = req['duration_ms']

        while in_flight_heap and in_flight_heap[0][0] <= t:
            f_time, k_f = heapq.heappop(in_flight_heap)
            if k_f in in_flight and in_flight[k_f]['finish_time'] == f_time:
                completed_cache[k_f] = in_flight[k_f]
                del in_flight[k_f]

        if k == "NONE":
            bal = idem_balances.get(u, 0)
            if bal >= amt:
                idem_balances[u] = bal - amt
                status = "SUCCESS"
                idem_success += 1
            else:
                status = "INSUFFICIENT_FUNDS"
                idem_fail += 1
            idem_statuses[rid] = status
            continue

        if k in in_flight:
            conflict_in_flight += 1
            idem_statuses[rid] = "CONFLICT_IN_FLIGHT"
            continue

        if k in completed_cache:
            entry = completed_cache[k]
            if t > entry['finish_time'] + ttl_ms:
                del completed_cache[k]
            else:
                if entry['payload']['user_id'] != u or entry['payload']['amount'] != amt:
                    mismatches += 1
                    idem_statuses[rid] = "PAYLOAD_MISMATCH"
                else:
                    cached_resp += 1
                    if entry['result']['status'] == "SUCCESS":
                        idem_statuses[rid] = "CACHED_SUCCESS"
                    else:
                        idem_statuses[rid] = "CACHED_INSUFFICIENT_FUNDS"
                continue

        bal = idem_balances.get(u, 0)
        finish_t = t + dur
        if bal >= amt:
            idem_balances[u] = bal - amt
            res = {"status": "SUCCESS"}
            status = "SUCCESS"
            idem_success += 1
        else:
            res = {"status": "INSUFFICIENT_FUNDS"}
            status = "INSUFFICIENT_FUNDS"
            idem_fail += 1

        in_flight[k] = {
            'finish_time': finish_t,
            'result': res,
            'payload': {'user_id': u, 'amount': amt}
        }
        heapq.heappush(in_flight_heap, (finish_t, k))
        idem_statuses[rid] = status

    for req in raw_requests:
        rid = req['req_id']
        sys.stdout.write(f"REQ {rid} NAIVE:{naive_statuses[rid]} IDEM:{idem_statuses[rid]}\n")

    sys.stdout.write(f"SUMMARY NAIVE CHARGES:{naive_success} DUP_CHARGES:{naive_dup} OVERCHARGED:{naive_overcharged}\n")
    sys.stdout.write(f"SUMMARY IDEM CHARGES:{idem_success} CACHED:{cached_resp} CONFLICTS:{conflict_in_flight} MISMATCHES:{mismatches}\n")
    sys.stdout.write(f"SUMMARY FINANCIAL_LOSS_PREVENTED:{naive_overcharged} DUP_CHARGES_PREVENTED:{naive_dup}\n")

if __name__ == '__main__':
    solve()
