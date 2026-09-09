import sys

def get_horizon(active_txs, tx_seq_map, global_tx_seq):
    if not active_txs:
        return "NONE", global_tx_seq + 1
    min_tx = min(active_txs, key=lambda t: tx_seq_map[t])
    return min_tx, tx_seq_map[min_tx]

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    page_capacity = 4
    actions = []
    mode = "CONFIG"

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "PAGE_CAPACITY":
                page_capacity = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    tx_seq_map = {}
    tx_id_by_seq = {}
    active_txs = set()
    global_tx_seq = 0

    tuples = []
    key_to_live_tuple_id = {}

    total_reclaimed = 0
    vacuum_blocked_ever = False

    out_lines = []
    act_idx = 1

    for act in actions:
        cmd = act[0]

        if cmd == "BEGIN":
            tx_id = act[1]
            if tx_id not in tx_seq_map:
                global_tx_seq += 1
                tx_seq_map[tx_id] = global_tx_seq
                tx_id_by_seq[global_tx_seq] = tx_id
            active_txs.add(tx_id)
            h_tx, h_seq = get_horizon(active_txs, tx_seq_map, global_tx_seq)
            out_lines.append(f"ACT {act_idx} BEGIN {tx_id} ACTIVE_TXS:{len(active_txs)} XMIN_HORIZON:{h_tx}")

        elif cmd == "INSERT":
            tx_id = act[1]
            key = act[2]
            val = act[3]
            tx_seq = tx_seq_map[tx_id]
            t_id = len(tuples) + 1
            p_id = (t_id - 1) // page_capacity
            tup = {
                'id': t_id,
                'key': key,
                'val': val,
                'xmin': tx_seq,
                'xmax': 0,
                'state': 'LIVE'
            }
            tuples.append(tup)
            key_to_live_tuple_id[key] = t_id
            out_lines.append(f"ACT {act_idx} INSERT {tx_id} KEY:{key} VAL:{val} TUPLE_ID:{t_id} PAGE:{p_id}")

        elif cmd == "UPDATE":
            tx_id = act[1]
            key = act[2]
            val = act[3]
            tx_seq = tx_seq_map[tx_id]
            old_t_id = key_to_live_tuple_id[key]
            old_tup = tuples[old_t_id - 1]
            old_tup['xmax'] = tx_seq
            old_tup['state'] = 'DEAD'

            new_t_id = len(tuples) + 1
            new_p_id = (new_t_id - 1) // page_capacity
            new_tup = {
                'id': new_t_id,
                'key': key,
                'val': val,
                'xmin': tx_seq,
                'xmax': 0,
                'state': 'LIVE'
            }
            tuples.append(new_tup)
            key_to_live_tuple_id[key] = new_t_id
            out_lines.append(f"ACT {act_idx} UPDATE {tx_id} KEY:{key} VAL:{val} OLD_TUPLE:{old_t_id} NEW_TUPLE:{new_t_id} PAGE:{new_p_id}")

        elif cmd == "DELETE":
            tx_id = act[1]
            key = act[2]
            tx_seq = tx_seq_map[tx_id]
            t_id = key_to_live_tuple_id.pop(key)
            tup = tuples[t_id - 1]
            tup['xmax'] = tx_seq
            tup['state'] = 'DEAD'
            out_lines.append(f"ACT {act_idx} DELETE {tx_id} KEY:{key} DEAD_TUPLE:{t_id}")

        elif cmd == "COMMIT":
            tx_id = act[1]
            active_txs.discard(tx_id)
            h_tx, h_seq = get_horizon(active_txs, tx_seq_map, global_tx_seq)
            out_lines.append(f"ACT {act_idx} COMMIT {tx_id} ACTIVE_TXS:{len(active_txs)} XMIN_HORIZON:{h_tx}")

        elif cmd == "VACUUM":
            h_tx, h_seq = get_horizon(active_txs, tx_seq_map, global_tx_seq)
            reclaimed_this_run = 0
            blocked_dead = 0
            live_cnt = 0
            dead_cnt = 0

            for tup in tuples:
                if tup['state'] == 'DEAD':
                    if tup['xmax'] < h_seq:
                        tup['state'] = 'RECLAIMED'
                        reclaimed_this_run += 1
                    else:
                        blocked_dead += 1
                        dead_cnt += 1
                elif tup['state'] == 'LIVE':
                    live_cnt += 1

            total_reclaimed += reclaimed_this_run
            denom = live_cnt + dead_cnt
            bloat_pct = (dead_cnt / denom * 100.0) if denom > 0 else 0.0

            if blocked_dead > 0:
                vacuum_blocked_ever = True
                out_lines.append(f"ACT {act_idx} VACUUM RECLAIMED:{reclaimed_this_run} BLOCKED_DEAD:{blocked_dead} LIVE:{live_cnt} BLOAT:{bloat_pct:.1f}% [AUTOVACUUM_BLOCKED]")
            else:
                out_lines.append(f"ACT {act_idx} VACUUM RECLAIMED:{reclaimed_this_run} BLOCKED_DEAD:0 LIVE:{live_cnt} BLOAT:{bloat_pct:.1f}%")

        act_idx += 1

    total_pages = (len(tuples) + page_capacity - 1) // page_capacity if tuples else 0
    live_cnt = sum(1 for t in tuples if t['state'] == 'LIVE')
    dead_cnt = sum(1 for t in tuples if t['state'] == 'DEAD')
    denom = live_cnt + dead_cnt
    bloat_pct = (dead_cnt / denom * 100.0) if denom > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_ACTIONS:{len(actions)}")
    out_lines.append(f"SUMMARY TOTAL_PAGES:{total_pages}")
    out_lines.append(f"SUMMARY TOTAL_LIVE_TUPLES:{live_cnt}")
    out_lines.append(f"SUMMARY TOTAL_DEAD_TUPLES:{dead_cnt}")
    out_lines.append(f"SUMMARY TOTAL_RECLAIMED_TUPLES:{total_reclaimed}")
    out_lines.append(f"SUMMARY TABLE_BLOAT_RATIO:{bloat_pct:.1f}%")
    out_lines.append(f"SUMMARY VACUUM_BLOCKED_INCIDENT: {'TRUE' if vacuum_blocked_ever else 'FALSE'}")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
