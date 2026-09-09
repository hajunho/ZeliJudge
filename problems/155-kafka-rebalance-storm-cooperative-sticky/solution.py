import json
import sys

def assign_eager_round_robin(partitions, active_consumers):
    if not active_consumers:
        return {str(p): None for p in partitions}
    sorted_consumers = sorted(active_consumers)
    assignment = {}
    for i, p in enumerate(sorted(partitions)):
        assignment[str(p)] = sorted_consumers[i % len(sorted_consumers)]
    return assignment

def assign_cooperative_sticky(partitions, current_assignment, active_consumers):
    if not active_consumers:
        return {str(p): None for p in partitions}
    sorted_consumers = sorted(active_consumers)
    num_p = len(partitions)
    num_c = len(sorted_consumers)
    target_min = num_p // num_c
    target_max = target_min + (1 if num_p % num_c != 0 else 0)

    new_assignment = {}
    consumer_partitions = {c: [] for c in sorted_consumers}
    unassigned = []

    # 1. Preserve existing assignments for active consumers up to target_max
    for p in sorted(partitions):
        curr_owner = current_assignment.get(str(p))
        if curr_owner in consumer_partitions:
            if len(consumer_partitions[curr_owner]) < target_max:
                consumer_partitions[curr_owner].append(p)
                new_assignment[str(p)] = curr_owner
            else:
                unassigned.append(p)
        else:
            unassigned.append(p)

    # 2. Assign remaining unassigned partitions to consumers with fewest partitions
    for p in unassigned:
        cand = min(sorted_consumers, key=lambda c: (len(consumer_partitions[c]), c))
        consumer_partitions[cand].append(p)
        new_assignment[str(p)] = cand

    return new_assignment

def solve(input_data):
    protocol = input_data.get("rebalance_protocol", "EAGER")
    num_partitions = int(input_data.get("num_partitions", 12))
    initial_consumers = list(input_data.get("initial_consumers", ["C1", "C2", "C3", "C4"]))
    sim_duration = int(input_data.get("simulation_duration_sec", 60))
    incoming_rate = float(input_data.get("incoming_rate_per_partition", 100.0))
    drain_rate = float(input_data.get("drain_rate_per_partition", 150.0))
    rebalance_duration = int(input_data.get("rebalance_duration_sec", 5))
    events = sorted(input_data.get("events", []), key=lambda e: e["time_sec"])

    partitions = list(range(num_partitions))
    active_consumers = set(initial_consumers)

    current_assignment = assign_eager_round_robin(partitions, active_consumers)
    
    lag = {p: 0.0 for p in partitions}
    peak_lag = 0.0
    total_stw_pause_sec = 0.0
    total_migrations = 0
    total_processed_records = 0.0

    rebalance_state = None
    event_idx = 0
    total_rebalances = 0

    for t in range(sim_duration):
        while event_idx < len(events) and events[event_idx]["time_sec"] == t:
            ev = events[event_idx]
            event_idx += 1
            total_rebalances += 1
            
            if ev["type"] == "CONSUMER_LEAVE":
                cid = ev["consumer_id"]
                if cid in active_consumers:
                    active_consumers.remove(cid)
            elif ev["type"] == "CONSUMER_JOIN":
                cid = ev["consumer_id"]
                active_consumers.add(cid)

            if protocol == "EAGER":
                target_assign = assign_eager_round_robin(partitions, active_consumers)
                rebalance_state = {
                    "end_time": t + rebalance_duration,
                    "target_assignment": target_assign,
                    "active_processing": {p: False for p in partitions}
                }
                total_stw_pause_sec += rebalance_duration
            else: # COOPERATIVE_STICKY
                target_assign = assign_cooperative_sticky(partitions, current_assignment, active_consumers)
                active_proc = {}
                for p in partitions:
                    curr_owner = current_assignment.get(str(p))
                    if curr_owner in active_consumers and target_assign.get(str(p)) == curr_owner:
                        active_proc[p] = True
                    else:
                        active_proc[p] = False
                
                rebalance_state = {
                    "end_time": t + rebalance_duration,
                    "target_assignment": target_assign,
                    "active_processing": active_proc
                }

        for p in partitions:
            lag[p] += incoming_rate
            
            can_drain = False
            if rebalance_state is not None:
                can_drain = rebalance_state["active_processing"].get(p, False)
            else:
                can_drain = (current_assignment.get(str(p)) in active_consumers)

            if can_drain:
                processed = min(lag[p], drain_rate)
                lag[p] -= processed
                total_processed_records += processed

        current_total_lag = sum(lag.values())
        if current_total_lag > peak_lag:
            peak_lag = current_total_lag

        if rebalance_state is not None and (t + 1) >= rebalance_state["end_time"]:
            old_assignment = current_assignment
            current_assignment = rebalance_state["target_assignment"]
            
            for p in partitions:
                old_owner = old_assignment.get(str(p))
                new_owner = current_assignment.get(str(p))
                if old_owner != new_owner:
                    total_migrations += 1

            rebalance_state = None

    final_lag = sum(lag.values())

    if protocol == "EAGER":
        diag = f"CRITICAL: Eager rebalance caused global Stop-The-World pause ({total_stw_pause_sec:.1f}s). {total_migrations} partition migrations disrupted caches, peaking lag at {peak_lag:,.0f}."
    else:
        diag = f"OPTIMAL: Cooperative Sticky assignor eliminated global STW pause (0.0s). Preserved locality with only {total_migrations} necessary migrations, keeping peak lag at {peak_lag:,.0f}."

    return {
        "protocol": protocol,
        "metrics": {
            "total_rebalances": total_rebalances,
            "total_stw_pause_sec": round(total_stw_pause_sec, 2),
            "total_migrations": total_migrations,
            "peak_lag": round(peak_lag, 2),
            "final_lag": round(final_lag, 2),
            "total_processed_records": round(total_processed_records, 2)
        },
        "final_assignment": current_assignment,
        "diagnosis": diag
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
