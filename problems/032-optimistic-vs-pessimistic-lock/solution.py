#!/usr/bin/env python3
import sys
import heapq

class Transaction:
    def __init__(self, idx, tx_id, read_time, delta_price, delta_stock, duration):
        self.idx = idx
        self.tx_id = tx_id
        self.read_time = read_time
        self.delta_price = delta_price
        self.delta_stock = delta_stock
        self.duration = duration
        self.commit_time = read_time + duration

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)

    cmd = next(it)  # INIT_ITEM
    item_id = next(it)
    init_price = int(next(it))
    init_stock = int(next(it))

    N = int(next(it))
    tx_list = []
    for i in range(N):
        op = next(it)  # TX
        tid = next(it)
        r_time = int(next(it))
        d_p = int(next(it))
        d_s = int(next(it))
        dur = int(next(it))
        tx_list.append(Transaction(i, tid, r_time, d_p, d_s, dur))

    # 1. NAIVE ?????
    # ???: (time, priority, type, tx_idx)
    # priority 1: COMMIT, priority 2: READ
    events_naive = []
    for t in tx_list:
        events_naive.append((t.read_time, 2, 'READ', t.idx))
        commit_priority = 3 if t.duration == 0 else 1
        events_naive.append((t.commit_time, commit_priority, 'COMMIT', t.idx))
    heapq.heapify(events_naive)

    n_price = init_price
    n_stock = init_stock
    tx_read_snap = [None] * N
    commit_order = []

    while events_naive:
        cur_t, _, ev_type, idx = heapq.heappop(events_naive)
        t = tx_list[idx]
        if ev_type == 'READ':
            tx_read_snap[idx] = (n_price, n_stock)
        elif ev_type == 'COMMIT':
            r_p, r_s = tx_read_snap[idx]
            n_price = r_p + t.delta_price
            n_stock = r_s + t.delta_stock
            commit_order.append(idx)

    # ?? ??(Lost Updates) ?? (O(N) Suffix Min ???):
    # ?? ???? A? ??? ?, A?? ?? ??? ?? ???? B?
    # A? ?? ?? ??(?? ??)? ?? ??(read_time <= commit_time_A)? ???? ????? A? ???.
    M_len = len(commit_order)
    suffix_min_read = [float('inf')] * (M_len + 1)
    for i in range(M_len - 1, -1, -1):
        suffix_min_read[i] = min(suffix_min_read[i + 1], tx_list[commit_order[i]].read_time)

    lost_count = 0
    for i in range(M_len - 1):
        idx_a = commit_order[i]
        if suffix_min_read[i + 1] <= tx_list[idx_a].commit_time:
            lost_count += 1

    # 2. OPTIMISTIC ?????
    events_opt = []
    for t in tx_list:
        events_opt.append((t.read_time, 2, 'READ', t.idx))
        commit_priority = 3 if t.duration == 0 else 1
        events_opt.append((t.commit_time, commit_priority, 'COMMIT', t.idx))
    heapq.heapify(events_opt)

    o_price = init_price
    o_stock = init_stock
    o_version = 1
    tx_read_ver = [None] * N
    opt_status = [None] * N
    opt_commits = 0
    opt_conflicts = 0

    while events_opt:
        cur_t, _, ev_type, idx = heapq.heappop(events_opt)
        t = tx_list[idx]
        if ev_type == 'READ':
            tx_read_ver[idx] = o_version
        elif ev_type == 'COMMIT':
            if tx_read_ver[idx] == o_version:
                o_price += t.delta_price
                o_stock += t.delta_stock
                o_version += 1
                opt_status[idx] = 'COMMIT'
                opt_commits += 1
            else:
                opt_status[idx] = 'CONFLICT'
                opt_conflicts += 1

    # 3. PESSIMISTIC ?????
    p_price = init_price
    p_stock = init_stock
    p_version = 1
    lock_avail = 0
    pess_wait = [0] * N
    total_wait = 0

    # read_time ???? ??
    for t in tx_list:
        t_acq = max(t.read_time, lock_avail)
        w = t_acq - t.read_time
        pess_wait[t.idx] = w
        total_wait += w
        lock_avail = t_acq + t.duration
        p_price += t.delta_price
        p_stock += t.delta_stock
        p_version += 1

    # 4. ?? ??
    for t in tx_list:
        o_st = opt_status[t.idx]
        w = pess_wait[t.idx]
        print(f"TX {t.tx_id} NAIVE:SUCCESS OPTIMISTIC:{o_st} PESSIMISTIC:COMMIT WAIT:{w}ms")

    print(f"SUMMARY NAIVE FINAL_PRICE:{n_price} FINAL_STOCK:{n_stock} LOST_UPDATES:{lost_count}")
    print(f"SUMMARY OPTIMISTIC COMMITS:{opt_commits}/{N} CONFLICTS:{opt_conflicts}/{N} FINAL_PRICE:{o_price} FINAL_STOCK:{o_stock} FINAL_VERSION:{o_version}")
    print(f"SUMMARY PESSIMISTIC COMMITS:{N}/{N} TOTAL_WAIT:{total_wait}ms FINAL_PRICE:{p_price} FINAL_STOCK:{p_stock} FINAL_VERSION:{p_version}")

if __name__ == '__main__':
    solve()
