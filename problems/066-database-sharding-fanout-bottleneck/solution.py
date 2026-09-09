import sys

def get_shard(key, s):
    val = sum((i + 1) * ord(c) for i, c in enumerate(str(key)))
    return val % s

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    num_shards = 4
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
            if parts[0] == "SHARDS":
                num_shards = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    S = num_shards
    all_shards_list = [f"S{i}" for i in range(S)]

    # Storage for Strategy A: Date-Based Sharding
    # shard_id -> list of (order_id, user_id, created_date, amount)
    date_shards = {i: [] for i in range(S)}

    # Storage for Strategy B: User-Based Sharding
    user_shards = {i: [] for i in range(S)}

    out_lines = []
    act_idx = 1

    date_total_fanout = 0
    date_max_fanout = 0

    user_total_fanout = 0
    user_max_fanout = 0

    total_query_count = 0
    consistency_passed = True

    for act in actions:
        cmd = act[0]

        if cmd == "INSERT":
            oid = act[1]
            uid = act[2]
            dt = act[3]
            amt = int(act[4])

            # Date-based placement
            d_shard = get_shard(dt, S)
            date_shards[d_shard].append((oid, uid, dt, amt))

            # User-based placement
            u_shard = get_shard(uid, S)
            user_shards[u_shard].append((oid, uid, dt, amt))

            out_lines.append(f"ACT {act_idx} INSERT {oid} DATE_SHARD:STORED_AT=S{d_shard} USER_SHARD:STORED_AT=S{u_shard}")

        elif cmd == "QUERY_BY_USER":
            uid = act[1]
            total_query_count += 1

            # Date-based: Scatter-Gather to ALL shards
            d_fanout = S
            d_targets = all_shards_list
            d_matches = []
            for s_id in range(S):
                for o in date_shards[s_id]:
                    if o[1] == uid:
                        d_matches.append(o[0])

            # User-based: Targeted single shard
            u_fanout = 1
            u_target_id = get_shard(uid, S)
            u_targets = [f"S{u_target_id}"]
            u_matches = []
            for o in user_shards[u_target_id]:
                if o[1] == uid:
                    u_matches.append(o[0])

            if sorted(d_matches) != sorted(u_matches):
                consistency_passed = False

            date_total_fanout += d_fanout
            date_max_fanout = max(date_max_fanout, d_fanout)
            user_total_fanout += u_fanout
            user_max_fanout = max(user_max_fanout, u_fanout)

            out_lines.append(f"ACT {act_idx} QUERY_BY_USER {uid}")
            out_lines.append(f"  DATE_SHARD: FANOUT:{d_fanout} TARGETS:[{','.join(d_targets)}] MATCHES:{len(d_matches)}")
            out_lines.append(f"  USER_SHARD: FANOUT:{u_fanout} TARGETS:[{','.join(u_targets)}] MATCHES:{len(u_matches)}")

        elif cmd == "QUERY_BY_DATE":
            dt = act[1]
            total_query_count += 1

            # Date-based: Targeted single shard
            d_fanout = 1
            d_target_id = get_shard(dt, S)
            d_targets = [f"S{d_target_id}"]
            d_matches = []
            for o in date_shards[d_target_id]:
                if o[2] == dt:
                    d_matches.append(o[0])

            # User-based: Scatter-Gather to ALL shards
            u_fanout = S
            u_targets = all_shards_list
            u_matches = []
            for s_id in range(S):
                for o in user_shards[s_id]:
                    if o[2] == dt:
                        u_matches.append(o[0])

            if sorted(d_matches) != sorted(u_matches):
                consistency_passed = False

            date_total_fanout += d_fanout
            date_max_fanout = max(date_max_fanout, d_fanout)
            user_total_fanout += u_fanout
            user_max_fanout = max(user_max_fanout, u_fanout)

            out_lines.append(f"ACT {act_idx} QUERY_BY_DATE {dt}")
            out_lines.append(f"  DATE_SHARD: FANOUT:{d_fanout} TARGETS:[{','.join(d_targets)}] MATCHES:{len(d_matches)}")
            out_lines.append(f"  USER_SHARD: FANOUT:{u_fanout} TARGETS:[{','.join(u_targets)}] MATCHES:{len(u_matches)}")

        elif cmd == "QUERY_BY_USER_AND_DATE":
            uid = act[1]
            dt = act[2]
            total_query_count += 1

            # Date-based: Targeted by date
            d_fanout = 1
            d_target_id = get_shard(dt, S)
            d_targets = [f"S{d_target_id}"]
            d_matches = []
            for o in date_shards[d_target_id]:
                if o[1] == uid and o[2] == dt:
                    d_matches.append(o[0])

            # User-based: Targeted by user
            u_fanout = 1
            u_target_id = get_shard(uid, S)
            u_targets = [f"S{u_target_id}"]
            u_matches = []
            for o in user_shards[u_target_id]:
                if o[1] == uid and o[2] == dt:
                    u_matches.append(o[0])

            if sorted(d_matches) != sorted(u_matches):
                consistency_passed = False

            date_total_fanout += d_fanout
            date_max_fanout = max(date_max_fanout, d_fanout)
            user_total_fanout += u_fanout
            user_max_fanout = max(user_max_fanout, u_fanout)

            out_lines.append(f"ACT {act_idx} QUERY_BY_USER_AND_DATE {uid} {dt}")
            out_lines.append(f"  DATE_SHARD: FANOUT:{d_fanout} TARGETS:[{','.join(d_targets)}] MATCHES:{len(d_matches)}")
            out_lines.append(f"  USER_SHARD: FANOUT:{u_fanout} TARGETS:[{','.join(u_targets)}] MATCHES:{len(u_matches)}")

        act_idx += 1

    # Summaries
    d_avg = (date_total_fanout / total_query_count) if total_query_count > 0 else 0.0
    u_avg = (user_total_fanout / total_query_count) if total_query_count > 0 else 0.0

    out_lines.append(f"SUMMARY DATE_SHARD TOTAL_FANOUT_QUERIES:{date_total_fanout} AVG_FANOUT:{d_avg:.2f} MAX_FANOUT:{date_max_fanout}")
    out_lines.append(f"SUMMARY USER_SHARD TOTAL_FANOUT_QUERIES:{user_total_fanout} AVG_FANOUT:{u_avg:.2f} MAX_FANOUT:{user_max_fanout}")

    diff = date_total_fanout - user_total_fanout
    eff = (diff / date_total_fanout * 100.0) if date_total_fanout > 0 else 0.0
    out_lines.append(f"SUMMARY FANOUT_SAVED:{diff} (EFFICIENCY:{eff:.2f}%)")

    consistency_str = "100% MATCHED" if consistency_passed else "MISMATCH_DETECTED"
    out_lines.append(f"SUMMARY DATA_CONSISTENCY_CHECK: {consistency_str}")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
