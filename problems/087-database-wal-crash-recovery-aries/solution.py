import sys
from collections import defaultdict

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    initial_disk = {}
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
            if parts[0] == "INITIAL_DATA":
                for item in parts[1:]:
                    if ":" in item:
                        k, v = item.split(":", 1)
                        initial_disk[k] = int(v)
        elif mode == "ACTIONS":
            actions.append(parts)

    disk = dict(initial_disk)
    buffer_pool = dict(initial_disk)
    wal = []
    lsn = 0

    active_txs = set()
    tx_updates = defaultdict(list)
    crash_count = 0
    total_redo_ops = 0
    total_undo_ops = 0

    out_lines = []
    act_idx = 1

    for act in actions:
        cmd = act[0]

        if cmd == "START":
            tx_id = act[1]
            lsn += 1
            active_txs.add(tx_id)
            wal.append({"lsn": lsn, "type": "START", "tx": tx_id})
            out_lines.append(f"ACT {act_idx} LSN:{lsn} START {tx_id}")

        elif cmd == "UPDATE":
            tx_id = act[1]
            key = act[2]
            new_val = int(act[3])

            old_val = buffer_pool.get(key, "NONE")
            buffer_pool[key] = new_val

            lsn += 1
            rec = {
                "lsn": lsn,
                "type": "UPDATE",
                "tx": tx_id,
                "key": key,
                "old": old_val,
                "new": new_val
            }
            wal.append(rec)
            tx_updates[tx_id].append(rec)
            out_lines.append(f"ACT {act_idx} LSN:{lsn} UPDATE {tx_id} KEY:{key} OLD:{old_val} NEW:{new_val}")

        elif cmd == "COMMIT":
            tx_id = act[1]
            lsn += 1
            active_txs.discard(tx_id)
            wal.append({"lsn": lsn, "type": "COMMIT", "tx": tx_id})
            out_lines.append(f"ACT {act_idx} LSN:{lsn} COMMIT {tx_id}")

        elif cmd == "ABORT":
            tx_id = act[1]
            lsn += 1
            active_txs.discard(tx_id)
            # Revert all uncommitted updates of this transaction
            for rec in reversed(tx_updates[tx_id]):
                k = rec["key"]
                old = rec["old"]
                if old == "NONE":
                    buffer_pool.pop(k, None)
                else:
                    buffer_pool[k] = old
            wal.append({"lsn": lsn, "type": "ABORT", "tx": tx_id})
            out_lines.append(f"ACT {act_idx} LSN:{lsn} ABORT {tx_id}")

        elif cmd == "CHECKPOINT":
            lsn += 1
            disk = dict(buffer_pool)
            sorted_active = sorted(list(active_txs))
            wal.append({"lsn": lsn, "type": "CHECKPOINT", "active_txs": sorted_active})
            out_lines.append(f"ACT {act_idx} LSN:{lsn} CHECKPOINT ACTIVE_TXS:[{','.join(sorted_active)}]")

        elif cmd == "CRASH":
            crash_count += 1
            buffer_pool = {}
            active_txs = set()
            out_lines.append(f"ACT {act_idx} CRASH VOLATILE_RAM_LOST")

        elif cmd == "RECOVER":
            out_lines.append(f"ACT {act_idx} RECOVER")

            # Locate most recent CHECKPOINT
            last_cp_rec = None
            last_cp_idx = -1
            for idx, rec in enumerate(wal):
                if rec["type"] == "CHECKPOINT":
                    last_cp_rec = rec
                    last_cp_idx = idx

            cp_lsn_str = str(last_cp_rec["lsn"]) if last_cp_rec else "NONE"
            scan_start_idx = (last_cp_idx + 1) if last_cp_rec else 0

            # Phase 1: Analysis
            current_active = set(last_cp_rec["active_txs"]) if last_cp_rec else set()
            winners = set()
            for idx in range(scan_start_idx, len(wal)):
                rec = wal[idx]
                if rec["type"] == "START":
                    current_active.add(rec["tx"])
                elif rec["type"] == "COMMIT":
                    current_active.discard(rec["tx"])
                    winners.add(rec["tx"])
                elif rec["type"] == "ABORT":
                    current_active.discard(rec["tx"])

            losers = set(current_active)
            sorted_winners = sorted(list(winners))
            sorted_losers = sorted(list(losers))
            out_lines.append(f"  PHASE_1_ANALYSIS LAST_CP_LSN:{cp_lsn_str} WINNERS:[{','.join(sorted_winners)}] LOSERS:[{','.join(sorted_losers)}]")

            # Phase 2: Redo (Repeating History starting from scan_start_idx)
            db = dict(disk)
            redo_records = []
            for idx in range(scan_start_idx, len(wal)):
                rec = wal[idx]
                if rec["type"] == "UPDATE":
                    redo_records.append(rec)

            if not redo_records:
                out_lines.append("  PHASE_2_REDO NONE")
            else:
                for rec in redo_records:
                    total_redo_ops += 1
                    db[rec["key"]] = rec["new"]
                    out_lines.append(f"  PHASE_2_REDO LSN:{rec['lsn']} TX:{rec['tx']} KEY:{rec['key']} VAL:{rec['new']}")

            # Phase 3: Undo (Rolling Back Losers backward through entire WAL)
            undo_ops = []
            for idx in range(len(wal) - 1, -1, -1):
                rec = wal[idx]
                if rec["type"] == "UPDATE" and rec["tx"] in losers:
                    undo_ops.append(rec)

            if not undo_ops:
                out_lines.append("  PHASE_3_UNDO NONE")
            else:
                for rec in undo_ops:
                    total_undo_ops += 1
                    old = rec["old"]
                    if old == "NONE":
                        db.pop(rec["key"], None)
                    else:
                        db[rec["key"]] = old
                    out_lines.append(f"  PHASE_3_UNDO LSN:{rec['lsn']} TX:{rec['tx']} KEY:{rec['key']} RESTORED:{old}")

            # Complete
            disk = dict(db)
            buffer_pool = dict(db)
            sorted_final = [f"{k}={db[k]}" for k in sorted(db.keys())]
            out_lines.append(f"  RECOVERY_COMPLETE FINAL_STATE:[{','.join(sorted_final)}]")

        act_idx += 1

    sorted_final = [f"{k}={buffer_pool[k]}" for k in sorted(buffer_pool.keys())]
    out_lines.append(f"SUMMARY TOTAL_ACTIONS:{len(actions)}")
    out_lines.append(f"SUMMARY TOTAL_WAL_RECORDS:{lsn}")
    out_lines.append(f"SUMMARY CRASH_COUNT:{crash_count}")
    out_lines.append(f"SUMMARY TOTAL_REDO_OPS:{total_redo_ops}")
    out_lines.append(f"SUMMARY TOTAL_UNDO_OPS:{total_undo_ops}")
    out_lines.append(f"SUMMARY FINAL_DATABASE_STATE:[{','.join(sorted_final)}]")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
