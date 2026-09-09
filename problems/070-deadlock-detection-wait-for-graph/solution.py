import sys

def get_tx_num(tx_id):
    num_part = "".join(filter(str.isdigit, tx_id))
    return int(num_part) if num_part else 0

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    timeout_ticks = 50
    actions = []

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
            if parts[0] == "LOCK_TIMEOUT_TICKS":
                timeout_ticks = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    # =========================================================================
    # State for Naive Engine
    # =========================================================================
    n_tx_cost = {}          # tx_id -> cost
    n_tx_status = {}        # tx_id -> "ACTIVE", "COMMITTED", "TIMEOUT_ROLLBACK", "ABORTED"
    n_held_locks = {}       # tx_id -> set of res_id
    n_lock_holder = {}      # res_id -> tx_id
    n_waiting_queue = {}    # res_id -> list of tx_id
    n_wait_info = {}        # tx_id -> {"res": res_id, "ticks": 0}
    n_total_blocked_ticks = 0
    n_timeout_rollbacks = 0

    # =========================================================================
    # State for Detector Engine
    # =========================================================================
    d_tx_cost = {}          # tx_id -> cost
    d_tx_status = {}        # tx_id -> "ACTIVE", "COMMITTED", "DEADLOCK_ROLLBACK", "ABORTED"
    d_held_locks = {}       # tx_id -> set of res_id
    d_lock_holder = {}      # res_id -> tx_id
    d_waiting_queue = {}    # res_id -> list of tx_id
    d_wait_info = {}        # tx_id -> {"res": res_id, "ticks": 0}
    d_total_blocked_ticks = 0
    d_deadlock_resolved = 0

    out_lines = []

    def find_cycle_from(start_tx):
        # Directed edge: waiter -> holder
        # Wait-for graph
        visited = []
        curr = start_tx
        while curr:
            if curr in visited:
                idx = visited.index(curr)
                return visited[idx:]  # Cycle found!
            visited.append(curr)
            if curr in d_wait_info:
                target_res = d_wait_info[curr]["res"]
                holder = d_lock_holder.get(target_res)
                curr = holder
            else:
                curr = None
        return None

    def rollback_detector_tx(v_tx, reason="DEADLOCK_ROLLBACK"):
        nonlocal d_deadlock_resolved
        d_tx_status[v_tx] = reason
        if reason == "DEADLOCK_ROLLBACK":
            d_deadlock_resolved += 1

        # 1. If v_tx was waiting for a lock, remove from waiting queue
        if v_tx in d_wait_info:
            w_res = d_wait_info[v_tx]["res"]
            if w_res in d_waiting_queue and v_tx in d_waiting_queue[w_res]:
                d_waiting_queue[w_res].remove(v_tx)
            del d_wait_info[v_tx]

        # 2. Release all locks held by v_tx and grant to next waiters
        released = list(d_held_locks.get(v_tx, set()))
        d_held_locks[v_tx] = set()
        for r_id in released:
            if d_lock_holder.get(r_id) == v_tx:
                del d_lock_holder[r_id]
                # Grant to next waiter if any
                while d_waiting_queue.get(r_id):
                    next_tx = d_waiting_queue[r_id].pop(0)
                    if d_tx_status.get(next_tx) == "ACTIVE":
                        d_lock_holder[r_id] = next_tx
                        d_held_locks.setdefault(next_tx, set()).add(r_id)
                        if next_tx in d_wait_info:
                            del d_wait_info[next_tx]
                        break

    def rollback_naive_tx(v_tx, reason="TIMEOUT_ROLLBACK"):
        nonlocal n_timeout_rollbacks
        n_tx_status[v_tx] = reason
        if reason == "TIMEOUT_ROLLBACK":
            n_timeout_rollbacks += 1

        if v_tx in n_wait_info:
            w_res = n_wait_info[v_tx]["res"]
            if w_res in n_waiting_queue and v_tx in n_waiting_queue[w_res]:
                n_waiting_queue[w_res].remove(v_tx)
            del n_wait_info[v_tx]

        released = list(n_held_locks.get(v_tx, set()))
        n_held_locks[v_tx] = set()
        for r_id in released:
            if n_lock_holder.get(r_id) == v_tx:
                del n_lock_holder[r_id]
                while n_waiting_queue.get(r_id):
                    next_tx = n_waiting_queue[r_id].pop(0)
                    if n_tx_status.get(next_tx) == "ACTIVE":
                        n_lock_holder[r_id] = next_tx
                        n_held_locks.setdefault(next_tx, set()).add(r_id)
                        if next_tx in n_wait_info:
                            del n_wait_info[next_tx]
                        break

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "START_TX":
            tx_id = act[1]
            cost = int(act[2])
            n_tx_cost[tx_id] = cost
            n_tx_status[tx_id] = "ACTIVE"
            n_held_locks[tx_id] = set()

            d_tx_cost[tx_id] = cost
            d_tx_status[tx_id] = "ACTIVE"
            d_held_locks[tx_id] = set()

            out_lines.append(f"ACT {act_idx} START_TX {tx_id} COST:{cost}")

        elif cmd == "ACQUIRE_LOCK":
            tx_id = act[1]
            res_id = act[2]

            # ---------------- Naive Engine ----------------
            n_res_str = ""
            if res_id not in n_lock_holder:
                n_lock_holder[res_id] = tx_id
                n_held_locks[tx_id].add(res_id)
                n_res_str = "GRANTED"
            else:
                holder = n_lock_holder[res_id]
                if holder == tx_id:
                    n_res_str = "GRANTED_ALREADY_HELD"
                else:
                    n_waiting_queue.setdefault(res_id, []).append(tx_id)
                    n_wait_info[tx_id] = {"res": res_id, "ticks": 0}
                    n_res_str = f"BLOCKED (WAITING_ON:{holder})"

            # ---------------- Detector Engine ----------------
            d_res_str = ""
            if res_id not in d_lock_holder:
                d_lock_holder[res_id] = tx_id
                d_held_locks[tx_id].add(res_id)
                d_res_str = "GRANTED"
            else:
                holder = d_lock_holder[res_id]
                if holder == tx_id:
                    d_res_str = "GRANTED_ALREADY_HELD"
                else:
                    # Register waiting
                    d_waiting_queue.setdefault(res_id, []).append(tx_id)
                    d_wait_info[tx_id] = {"res": res_id, "ticks": 0}

                    # Check for cycle in wait-for graph
                    cycle = find_cycle_from(tx_id)
                    if not cycle:
                        d_res_str = f"BLOCKED (WAIT_FOR:{holder})"
                    else:
                        # Deadlock detected! Select victim
                        # Rule: lowest cost, tie-break by larger tx_id number
                        victim = min(cycle, key=lambda t: (d_tx_cost[t], -get_tx_num(t)))
                        v_cost = d_tx_cost[victim]
                        cycle_path = "->".join(cycle + [cycle[0]])
                        d_res_str = f"DEADLOCK_DETECTED CYCLE:[{cycle_path}] VICTIM:{victim} (COST:{v_cost}) RESOLVED"

                        # Rollback victim
                        rollback_detector_tx(victim, reason="DEADLOCK_ROLLBACK")

            out_lines.append(f"ACT {act_idx} ACQUIRE_LOCK {tx_id} RES:{res_id}")
            out_lines.append(f"  NAIVE: {n_res_str}")
            out_lines.append(f"  DETECTOR: {d_res_str}")

        elif cmd == "RELEASE_LOCK":
            tx_id = act[1]
            res_id = act[2]

            # Naive
            if res_id in n_held_locks.get(tx_id, set()):
                n_held_locks[tx_id].remove(res_id)
                del n_lock_holder[res_id]
                while n_waiting_queue.get(res_id):
                    nxt = n_waiting_queue[res_id].pop(0)
                    if n_tx_status.get(nxt) == "ACTIVE":
                        n_lock_holder[res_id] = nxt
                        n_held_locks.setdefault(nxt, set()).add(res_id)
                        if nxt in n_wait_info:
                            del n_wait_info[nxt]
                        break

            # Detector
            if res_id in d_held_locks.get(tx_id, set()):
                d_held_locks[tx_id].remove(res_id)
                del d_lock_holder[res_id]
                while d_waiting_queue.get(res_id):
                    nxt = d_waiting_queue[res_id].pop(0)
                    if d_tx_status.get(nxt) == "ACTIVE":
                        d_lock_holder[res_id] = nxt
                        d_held_locks.setdefault(nxt, set()).add(res_id)
                        if nxt in d_wait_info:
                            del d_wait_info[nxt]
                        break

            out_lines.append(f"ACT {act_idx} RELEASE_LOCK {tx_id} RES:{res_id}")
            out_lines.append("  NAIVE: RELEASED")
            out_lines.append("  DETECTOR: RELEASED")

        elif cmd == "COMMIT_TX":
            tx_id = act[1]

            # Naive Commit
            n_released_count = 0
            if n_tx_status.get(tx_id) == "ACTIVE":
                n_tx_status[tx_id] = "COMMITTED"
                held = list(n_held_locks.get(tx_id, set()))
                n_released_count = len(held)
                n_held_locks[tx_id] = set()
                for r_id in held:
                    if n_lock_holder.get(r_id) == tx_id:
                        del n_lock_holder[r_id]
                        while n_waiting_queue.get(r_id):
                            nxt = n_waiting_queue[r_id].pop(0)
                            if n_tx_status.get(nxt) == "ACTIVE":
                                n_lock_holder[r_id] = nxt
                                n_held_locks.setdefault(nxt, set()).add(r_id)
                                if nxt in n_wait_info:
                                    del n_wait_info[nxt]
                                break

            # Detector Commit
            d_released_count = 0
            if d_tx_status.get(tx_id) == "ACTIVE":
                d_tx_status[tx_id] = "COMMITTED"
                held = list(d_held_locks.get(tx_id, set()))
                d_released_count = len(held)
                d_held_locks[tx_id] = set()
                for r_id in held:
                    if d_lock_holder.get(r_id) == tx_id:
                        del d_lock_holder[r_id]
                        while d_waiting_queue.get(r_id):
                            nxt = d_waiting_queue[r_id].pop(0)
                            if d_tx_status.get(nxt) == "ACTIVE":
                                d_lock_holder[r_id] = nxt
                                d_held_locks.setdefault(nxt, set()).add(r_id)
                                if nxt in d_wait_info:
                                    del d_wait_info[nxt]
                                break

            n_status_str = "COMMITTED" if n_tx_status.get(tx_id) == "COMMITTED" else f"FAILED_ALREADY_{n_tx_status.get(tx_id)}"
            d_status_str = "COMMITTED" if d_tx_status.get(tx_id) == "COMMITTED" else f"FAILED_ALREADY_{d_tx_status.get(tx_id)}"

            out_lines.append(f"ACT {act_idx} COMMIT_TX {tx_id}")
            out_lines.append(f"  NAIVE: {n_status_str} RELEASED_LOCKS:{n_released_count}")
            out_lines.append(f"  DETECTOR: {d_status_str} RELEASED_LOCKS:{d_released_count}")

        elif cmd == "TICK":
            ticks = int(act[1])

            # Naive Advance
            n_timeouts = 0
            # Accumulate blocked ticks
            n_total_blocked_ticks += ticks * len(n_wait_info)
            timed_out_txs = []
            for t, info in list(n_wait_info.items()):
                info["ticks"] += ticks
                if info["ticks"] >= timeout_ticks:
                    timed_out_txs.append(t)

            for t in timed_out_txs:
                rollback_naive_tx(t, reason="TIMEOUT_ROLLBACK")
                n_timeouts += 1

            # Detector Advance
            d_total_blocked_ticks += ticks * len(d_wait_info)
            d_timeouts = 0
            d_timed_out_txs = []
            for t, info in list(d_wait_info.items()):
                info["ticks"] += ticks
                if info["ticks"] >= timeout_ticks:
                    d_timed_out_txs.append(t)

            for t in d_timed_out_txs:
                rollback_detector_tx(t, reason="TIMEOUT_ROLLBACK")
                d_timeouts += 1

            out_lines.append(f"ACT {act_idx} TICK {ticks}")
            out_lines.append(f"  NAIVE: TIME_ADVANCED WAITING_TXS:{len(n_wait_info)} TIMEOUT_EVENTS:{n_timeouts}")
            out_lines.append(f"  DETECTOR: TIME_ADVANCED WAITING_TXS:{len(d_wait_info)} TIMEOUT_EVENTS:{d_timeouts}")

        elif cmd == "CHECK_STATUS":
            n_active = sum(1 for s in n_tx_status.values() if s == "ACTIVE")
            n_blocked = len(n_wait_info)
            d_active = sum(1 for s in d_tx_status.values() if s == "ACTIVE")
            d_blocked = len(d_wait_info)

            out_lines.append(f"ACT {act_idx} CHECK_STATUS")
            out_lines.append(f"  NAIVE: ACTIVE_TXS:{n_active} BLOCKED_TXS:{n_blocked} TOTAL_BLOCKED_TICKS:{n_total_blocked_ticks} TIMEOUT_ROLLBACKS:{n_timeout_rollbacks}")
            out_lines.append(f"  DETECTOR: ACTIVE_TXS:{d_active} BLOCKED_TXS:{d_blocked} TOTAL_BLOCKED_TICKS:{d_total_blocked_ticks} DEADLOCK_RESOLVED:{d_deadlock_resolved}")

    # Final Summary
    tot_tx = len(n_tx_status)
    saved_ticks = n_total_blocked_ticks - d_total_blocked_ticks
    reduction_pct = (saved_ticks / n_total_blocked_ticks * 100.0) if n_total_blocked_ticks > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_TRANSACTIONS:{tot_tx}")
    out_lines.append(f"SUMMARY NAIVE TOTAL_BLOCKED_TICKS:{n_total_blocked_ticks} TIMEOUT_ROLLBACKS:{n_timeout_rollbacks}")
    out_lines.append(f"SUMMARY DETECTOR TOTAL_BLOCKED_TICKS:{d_total_blocked_ticks} DEADLOCK_RESOLVED:{d_deadlock_resolved} 0_TICK_RECOVERIES:{d_deadlock_resolved}")
    out_lines.append(f"SUMMARY LATENCY_SAVED_TICKS:{saved_ticks} (BLOCKING_REDUCTION:{reduction_pct:.2f}%)")
    out_lines.append("SUMMARY ENGINE_VERDICT: DETECTOR_PREVENTS_SYSTEM_FREEZE")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
