import sys

def format_assignments(assignments):
    if not assignments:
        return "NONE"
    items = []
    for c in sorted(assignments.keys()):
        plist = sorted(assignments[c], key=lambda x: int(x[1:]))
        items.append(f"{c}=[{','.join(plist)}]")
    return ",".join(items)

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    num_partitions = 0
    events = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] == "NUM_PARTITIONS":
            num_partitions = int(parts[1])
        elif parts[0] in ("JOIN", "LEAVE"):
            events.append((parts[0], parts[1]))

    partitions = [f"P{i}" for i in range(num_partitions)]

    # State for Eager
    eager_consumers = set()
    eager_assignments = {} # c -> set of partitions
    eager_total_revocations = 0
    eager_total_migrations = 0

    # State for Cooperative Sticky
    sticky_consumers = set()
    sticky_assignments = {} # c -> set of partitions
    sticky_total_revocations = 0
    sticky_total_migrations = 0
    sticky_total_retained = 0

    out_lines = []

    for idx, (action, c_id) in enumerate(events, 1):
        out_lines.append(f"EVENT {idx} {action} {c_id}")

        # ----------------------------------------------------
        # 1. EAGER REBALANCE
        # ----------------------------------------------------
        old_eager = {c: set(plist) for c, plist in eager_assignments.items()}
        if action == "JOIN":
            eager_consumers.add(c_id)
        elif action == "LEAVE":
            eager_consumers.discard(c_id)

        active_eager = sorted(eager_consumers)
        m_eager = len(active_eager)

        # Step 1: Revoke ALL partitions from all remaining consumers
        eager_revoked = sum(len(plist) for plist in old_eager.values())
        eager_total_revocations += eager_revoked

        new_eager = {c: set() for c in active_eager}
        if m_eager > 0:
            for p_idx, p in enumerate(partitions):
                c = active_eager[p_idx % m_eager]
                new_eager[c].add(p)

        eager_migrated = sum(len(new_eager[c] - old_eager.get(c, set())) for c in active_eager)
        eager_total_migrations += eager_migrated
        eager_assignments = new_eager

        out_lines.append(f"  EAGER: REVOKED:{eager_revoked} MIGRATED:{eager_migrated} ASSIGNMENTS:{format_assignments(new_eager)}")

        # ----------------------------------------------------
        # 2. COOPERATIVE STICKY REBALANCE
        # ----------------------------------------------------
        old_sticky = {c: set(plist) for c, plist in sticky_assignments.items()}
        sticky_revoked = 0

        if action == "LEAVE":
            if c_id in sticky_consumers:
                sticky_consumers.discard(c_id)
                # Revoke leaving consumer's partitions
                leaving_parts = old_sticky.get(c_id, set())
                sticky_revoked += len(leaving_parts)
                if c_id in sticky_assignments:
                    del sticky_assignments[c_id]
        elif action == "JOIN":
            sticky_consumers.add(c_id)
            if c_id not in sticky_assignments:
                sticky_assignments[c_id] = set()

        active_sticky = sorted(sticky_consumers)
        m_sticky = len(active_sticky)

        if m_sticky == 0:
            new_sticky = {}
        else:
            base = num_partitions // m_sticky
            rem = num_partitions % m_sticky
            target_quotas = {}
            for i, c in enumerate(active_sticky):
                target_quotas[c] = base + (1 if i < rem else 0)

            # Cooperative Revocation: Only revoke excess from consumers holding more than quota
            for c in active_sticky:
                cur_parts = sorted(sticky_assignments.get(c, set()), key=lambda x: int(x[1:]))
                quota = target_quotas[c]
                if len(cur_parts) > quota:
                    excess_count = len(cur_parts) - quota
                    excess_parts = cur_parts[-excess_count:]
                    sticky_revoked += len(excess_parts)
                    sticky_assignments[c] = set(cur_parts[:-excess_count])

            # All currently unassigned partitions
            assigned_now = set().union(*sticky_assignments.values()) if sticky_assignments else set()
            unassigned_pool = sorted(list(set(partitions) - assigned_now), key=lambda x: int(x[1:]))

            # Allocation of unassigned partitions to consumers below quota
            unassigned_idx = 0
            for c in active_sticky:
                needed = target_quotas[c] - len(sticky_assignments[c])
                for _ in range(needed):
                    sticky_assignments[c].add(unassigned_pool[unassigned_idx])
                    unassigned_idx += 1

            new_sticky = {c: set(sticky_assignments[c]) for c in active_sticky}

        sticky_total_revocations += sticky_revoked
        sticky_retained = sum(len(new_sticky[c] & old_sticky.get(c, set())) for c in active_sticky)
        sticky_migrated = sum(len(new_sticky[c] - old_sticky.get(c, set())) for c in active_sticky)
        sticky_total_retained += sticky_retained
        sticky_total_migrations += sticky_migrated

        out_lines.append(f"  STICKY: REVOKED:{sticky_revoked} MIGRATED:{sticky_migrated} RETAINED:{sticky_retained} ASSIGNMENTS:{format_assignments(new_sticky)}")

    # Summary
    out_lines.append(f"SUMMARY EAGER TOTAL_REVOCATIONS:{eager_total_revocations} TOTAL_MIGRATIONS:{eager_total_migrations}")
    out_lines.append(f"SUMMARY STICKY TOTAL_REVOCATIONS:{sticky_total_revocations} TOTAL_MIGRATIONS:{sticky_total_migrations} TOTAL_RETAINED:{sticky_total_retained}")

    if eager_total_revocations > 0:
        saved = eager_total_revocations - sticky_total_revocations
        efficiency = (saved / eager_total_revocations) * 100.0
    else:
        saved = 0
        efficiency = 0.0

    out_lines.append(f"SUMMARY REVOCATIONS_SAVED:{saved} (EFFICIENCY:{efficiency:.2f}%)")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
