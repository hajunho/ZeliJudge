import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    # Hard State
    hard_users = {}       # id -> name
    hard_orders = []      # list of (order_id, user_id, amount)
    hard_cache = {}       # id -> name
    hard_lost_orders = 0
    hard_ghost_cache_hits = 0

    # Soft State
    soft_users = {}       # id -> {"name": name, "deleted": bool}
    soft_orders = []      # list of (order_id, user_id, amount)
    soft_cache = {}       # id -> name
    soft_restore_successes = 0

    total_orders_created = 0
    out_lines = []
    act_idx = 1

    for line in input_data:
        line = line.strip()
        if not line or line == "ACTIONS":
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "INSERT_USER":
            uid = parts[1]
            uname = parts[2]

            hard_users[uid] = uname
            hard_cache[uid] = uname

            soft_users[uid] = {"name": uname, "deleted": False}
            soft_cache[uid] = uname

            out_lines.append(f"ACT {act_idx} INSERT_USER {uid} HARD:OK SOFT:OK")

        elif cmd == "INSERT_ORDER":
            oid = parts[1]
            uid = parts[2]
            amt = int(parts[3])
            total_orders_created += 1

            # Hard
            if uid not in hard_users:
                hard_status = "FAIL_USER_NOT_FOUND"
            else:
                hard_orders.append((oid, uid, amt))
                hard_status = "OK"

            # Soft
            if uid not in soft_users:
                soft_status = "FAIL_USER_NOT_FOUND"
            elif soft_users[uid]["deleted"]:
                soft_status = "FAIL_USER_DELETED"
            else:
                soft_orders.append((oid, uid, amt))
                soft_status = "OK"

            out_lines.append(f"ACT {act_idx} INSERT_ORDER {oid} HARD:{hard_status} SOFT:{soft_status}")

        elif cmd == "DELETE_USER":
            uid = parts[1]

            # Hard: Cascade Delete orders & No Tombstone sent to cache!
            if uid in hard_users:
                del hard_users[uid]
                removed = [o for o in hard_orders if o[1] == uid]
                hard_orders = [o for o in hard_orders if o[1] != uid]
                hard_lost_orders += len(removed)
                hard_status = f"USER_DELETED_CASCADE({len(removed)})"
            else:
                hard_status = "NOT_FOUND"

            # Soft: Mark deleted_at & Send CDC Tombstone to cache!
            if uid in soft_users:
                if not soft_users[uid]["deleted"]:
                    soft_users[uid]["deleted"] = True
                    if uid in soft_cache:
                        del soft_cache[uid]
                    soft_status = "USER_SOFT_DELETED_TOMBSTONE_SENT"
                else:
                    soft_status = "ALREADY_DELETED"
            else:
                soft_status = "NOT_FOUND"

            out_lines.append(f"ACT {act_idx} DELETE_USER {uid} HARD:{hard_status} SOFT:{soft_status}")

        elif cmd == "RESTORE_USER":
            uid = parts[1]

            # Hard: Cannot restore deleted data!
            if uid in hard_users:
                hard_status = "ALREADY_ACTIVE"
            else:
                hard_status = "RESTORE_FAIL_NOT_FOUND"

            # Soft: Restore from soft delete & Rewarm cache!
            if uid in soft_users:
                if soft_users[uid]["deleted"]:
                    soft_users[uid]["deleted"] = False
                    soft_cache[uid] = soft_users[uid]["name"]
                    soft_restore_successes += 1
                    soft_status = "RESTORE_OK"
                else:
                    soft_status = "ALREADY_ACTIVE"
            else:
                soft_status = "NOT_FOUND"

            out_lines.append(f"ACT {act_idx} RESTORE_USER {uid} HARD:{hard_status} SOFT:{soft_status}")

        elif cmd == "QUERY_ACTIVE_USERS":
            # Hard
            active_hard = sorted(hard_users.keys())
            hard_status = f"COUNT={len(active_hard)},USERS=[{','.join(active_hard)}]"

            # Soft
            active_soft = sorted([u for u, data in soft_users.items() if not data["deleted"]])
            soft_status = f"COUNT={len(active_soft)},USERS=[{','.join(active_soft)}]"

            out_lines.append(f"ACT {act_idx} QUERY_ACTIVE_USERS HARD:{hard_status} SOFT:{soft_status}")

        elif cmd == "QUERY_AUDIT_ORDERS":
            uid = parts[1]

            # Hard
            u_orders_hard = [o for o in hard_orders if o[1] == uid]
            hard_cnt = len(u_orders_hard)
            hard_total = sum(o[2] for o in u_orders_hard)
            hard_status = f"ORDERS={hard_cnt},TOTAL={hard_total}"

            # Soft
            u_orders_soft = [o for o in soft_orders if o[1] == uid]
            soft_cnt = len(u_orders_soft)
            soft_total = sum(o[2] for o in u_orders_soft)
            soft_status = f"ORDERS={soft_cnt},TOTAL={soft_total}"

            out_lines.append(f"ACT {act_idx} QUERY_AUDIT_ORDERS {uid} HARD:{hard_status} SOFT:{soft_status}")

        elif cmd == "QUERY_CACHE":
            uid = parts[1]

            # Hard
            if uid in hard_cache:
                if uid not in hard_users:
                    hard_ghost_cache_hits += 1
                    hard_status = f"GHOST_CACHE_HIT(name={hard_cache[uid]})"
                else:
                    hard_status = f"CACHE_HIT(name={hard_cache[uid]})"
            else:
                hard_status = "CACHE_MISS"

            # Soft
            if uid in soft_cache:
                soft_status = f"CACHE_HIT(name={soft_cache[uid]})"
            else:
                if uid in soft_users and soft_users[uid]["deleted"]:
                    soft_status = "CACHE_CLEAN_MISS(TOMBSTONE_EVICTED)"
                else:
                    soft_status = "CACHE_MISS"

            out_lines.append(f"ACT {act_idx} QUERY_CACHE {uid} HARD:{hard_status} SOFT:{soft_status}")

        act_idx += 1

    # Summary
    hard_remaining = len(hard_orders)
    soft_remaining = len(soft_orders)

    out_lines.append(f"SUMMARY HARD REMAINING_ORDERS:{hard_remaining} LOST_ORDERS:{hard_lost_orders} GHOST_CACHE_HITS:{hard_ghost_cache_hits} RESTORE_SUCCESSES:0")
    out_lines.append(f"SUMMARY SOFT REMAINING_ORDERS:{soft_remaining} LOST_ORDERS:0 GHOST_CACHE_HITS:0 RESTORE_SUCCESSES:{soft_restore_successes}")

    if total_orders_created > 0:
        hard_rate = (hard_remaining / total_orders_created) * 100.0
        soft_rate = (soft_remaining / total_orders_created) * 100.0
    else:
        hard_rate = 100.0
        soft_rate = 100.0

    out_lines.append(f"SUMMARY DATA_RETENTION_RATE HARD:{hard_rate:.2f}% SOFT:{soft_rate:.2f}%")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
