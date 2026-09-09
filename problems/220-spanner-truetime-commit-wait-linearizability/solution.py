"""
Problem 220: Google Spanner TrueTime, Commit Wait, and Linearizability
"""
import sys
import json

def simulate_spanner_cluster(data):
    config = data.get("config", {})
    epsilon_ms = float(config.get("clock_uncertainty_epsilon_ms", 4.0))
    commit_wait_enabled = bool(config.get("commit_wait_enabled", True))
    lock_wait_timeout_ms = float(config.get("lock_wait_timeout_ms", 500.0))
    dc_offsets = config.get("datacenter_clock_offsets_ms", {})

    transactions = data.get("transactions", [])

    committed_txns = {}
    active_locks = {}
    dc_last_assigned = {}

    total_txns = len(transactions)
    committed_count = 0
    aborted_lock_timeouts = 0
    linearizability_violations = 0
    total_commit_wait_ms = 0.0
    total_txn_latency_ms = 0.0

    current_real_time_ms = 0.0

    for txn in transactions:
        tid = txn["id"]
        txn_type = txn.get("type", "READ_WRITE")
        dc = txn.get("datacenter", "us-east")
        offset = float(dc_offsets.get(dc, 0.0))
        offset = max(-epsilon_ms, min(epsilon_ms, offset))

        keys = txn.get("keys", ["k1"])
        arrival_time_ms = float(txn.get("arrival_time_ms", current_real_time_ms))
        current_real_time_ms = max(current_real_time_ms, arrival_time_ms)

        if txn_type == "SNAPSHOT_READ":
            read_ts = float(txn.get("read_timestamp_ms", current_real_time_ms + offset))
            # Check linearizability: any write committed in real time before this read arrived
            # must have its commit timestamp <= read_ts
            for c_id, c_data in committed_txns.items():
                if c_data["commit_real_time"] <= arrival_time_ms and any(k in c_data["keys"] for k in keys):
                    if c_data["commit_ts"] > read_ts:
                        linearizability_violations += 1
            committed_count += 1
            total_txn_latency_ms += 2.0
            continue

        # READ_WRITE
        lock_conflict = False
        max_conflict_release_time = current_real_time_ms

        for k in keys:
            if k in active_locks:
                lock_info = active_locks[k]
                if lock_info["lock_release_real_time"] > current_real_time_ms:
                    lock_conflict = True
                    if lock_info["lock_release_real_time"] > max_conflict_release_time:
                        max_conflict_release_time = lock_info["lock_release_real_time"]

        if lock_conflict:
            wait_time = max_conflict_release_time - current_real_time_ms
            if wait_time > lock_wait_timeout_ms:
                aborted_lock_timeouts += 1
                total_txn_latency_ms += lock_wait_timeout_ms
                continue
            else:
                current_real_time_ms = max_conflict_release_time
                total_txn_latency_ms += wait_time

        exec_duration_ms = float(txn.get("execution_duration_ms", 10.0))
        current_real_time_ms += exec_duration_ms
        t_prepare_real = current_real_time_ms
        local_time_prepare = t_prepare_real + offset

        # Pick commit timestamp s:
        # Each coordinator uses its local TT.now().latest and its local dc_last_assigned
        tt_latest = local_time_prepare + epsilon_ms
        last_assigned = dc_last_assigned.get(dc, 0.0)
        commit_ts = max(tt_latest, last_assigned + 0.1)
        dc_last_assigned[dc] = commit_ts

        # Commit Wait Rule:
        if commit_wait_enabled:
            # Must wait until local TT.now().earliest > commit_ts
            # local_time - epsilon > commit_ts => real_time + offset - epsilon > commit_ts
            # real_time > commit_ts + epsilon - offset
            t_release_real = commit_ts + epsilon_ms - offset
            wait_duration = max(0.0, t_release_real - current_real_time_ms)
            total_commit_wait_ms += wait_duration
            current_real_time_ms += wait_duration
        else:
            # Commit wait bypassed! Releases locks immediately at prepare time!
            t_release_real = current_real_time_ms
            # In some implementations, without commit wait, s is just local time
            commit_ts = local_time_prepare

        for k in keys:
            active_locks[k] = {
                "holder_txn_id": tid,
                "lock_release_real_time": t_release_real
            }

        committed_txns[tid] = {
            "commit_ts": commit_ts,
            "commit_real_time": current_real_time_ms,
            "keys": keys,
            "datacenter": dc
        }
        committed_count += 1
        total_txn_latency_ms += (current_real_time_ms - arrival_time_ms)

    # Check external consistency across all committed transactions
    c_list = list(committed_txns.values())
    for i in range(len(c_list)):
        for j in range(len(c_list)):
            if i != j:
                t1 = c_list[i]
                t2 = c_list[j]
                if t1["commit_real_time"] < t2["commit_real_time"]:
                    if any(k in t2["keys"] for k in t1["keys"]):
                        if t1["commit_ts"] >= t2["commit_ts"]:
                            linearizability_violations += 1

    avg_commit_wait = (total_commit_wait_ms / committed_count) if committed_count > 0 else 0.0
    avg_latency = (total_txn_latency_ms / total_txns) if total_txns > 0 else 0.0

    if linearizability_violations > 0:
        verdict = "STALE_SNAPSHOT_EXTERNAL_CONSISTENCY_VIOLATION"
        status = "FAILED"
    elif aborted_lock_timeouts > 0 or (epsilon_ms >= 50.0 and avg_commit_wait >= 100.0):
        verdict = "CLOCK_UNCERTAINTY_COMMIT_WAIT_COLLAPSE"
        status = "FAILED"
    elif epsilon_ms <= 7.0 and commit_wait_enabled and linearizability_violations == 0 and aborted_lock_timeouts == 0:
        verdict = "OPTIMAL_TRUETIME_COMMIT_WAIT_LINEARIZABILITY"
        status = "SUCCESS"
    else:
        verdict = "NORMAL_SPANNER_TRANSACTION_FLOW"
        status = "SUCCESS"

    return {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "clock_uncertainty_epsilon_ms": epsilon_ms,
            "commit_wait_enabled": commit_wait_enabled,
            "total_transactions": total_txns,
            "committed_transactions": committed_count,
            "aborted_lock_timeouts": aborted_lock_timeouts,
            "linearizability_violations": linearizability_violations,
            "average_commit_wait_ms": round(avg_commit_wait, 2),
            "average_transaction_latency_ms": round(avg_latency, 2)
        }
    }

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return
        data = json.loads(raw_input)
        result = simulate_spanner_cluster(data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
