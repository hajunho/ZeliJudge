import json
import sys

def solve(data):
    num_partitions = data.get("num_partitions", 4)
    consumers = data.get("consumers", ["c1", "c2"])
    assignor = data.get("assignor", "EAGER")
    max_poll_records = data.get("max_poll_records", 500)
    max_poll_interval_ms = data.get("max_poll_interval_ms", 300000)
    rebalance_duration_ms = data.get("rebalance_duration_ms", 10000)
    max_delivery_attempts = data.get("max_delivery_attempts", 3)
    
    partition_messages = data.get("partition_messages", {})
    
    total_messages = 0
    for p_str, msgs in partition_messages.items():
        total_messages += len(msgs)
        
    committed_offsets = {int(p): 0 for p in range(num_partitions)}
    message_attempts = {}
    
    processed_records_log = []
    dlq_records_log = []
    
    rebalance_events_count = 0
    max_poll_interval_violations = 0
    total_stw_freeze_ms = 0
    duplicate_processed_count = 0
    
    active_consumers = list(consumers)
    
    def assign_partitions(active_c_list):
        assignment = {c: [] for c in active_c_list}
        if not active_c_list:
            return assignment
        for p in range(num_partitions):
            c = active_c_list[p % len(active_c_list)]
            assignment[c].append(p)
        return assignment
        
    current_assignment = assign_partitions(active_consumers)
    
    max_iterations = 200
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        all_done = True
        for p in range(num_partitions):
            msgs = partition_messages.get(str(p), [])
            if committed_offsets[p] < len(msgs):
                all_done = False
                break
        if all_done:
            break
            
        rebalance_triggered = False
        kicked_consumer = None
        
        for c in list(active_consumers):
            assigned_ps = current_assignment.get(c, [])
            if not assigned_ps:
                continue
                
            batch = []
            for p in assigned_ps:
                msgs = partition_messages.get(str(p), [])
                start_off = committed_offsets[p]
                for m in msgs[start_off:]:
                    if len(batch) < max_poll_records:
                        batch.append((p, m))
                    else:
                        break
                if len(batch) >= max_poll_records:
                    break
                    
            if not batch:
                continue
                
            batch_proc_time = sum(m["proc_time_ms"] for p, m in batch)
            
            if batch_proc_time > max_poll_interval_ms:
                max_poll_interval_violations += 1
                rebalance_events_count += 1
                rebalance_triggered = True
                kicked_consumer = c
                
                accum_time = 0
                processed_in_batch = 0
                for p, m in batch:
                    key = (p, m["offset"])
                    message_attempts[key] = message_attempts.get(key, 0) + 1
                    accum_time += m["proc_time_ms"]
                    processed_in_batch += 1
                    
                    processed_records_log.append({
                        "consumer": c,
                        "partition": p,
                        "offset": m["offset"],
                        "status": "PROCESSED_UNCOMMITTED_DUE_TO_REBALANCE",
                        "attempt": message_attempts[key]
                    })
                    
                    if message_attempts[key] >= max_delivery_attempts:
                        dlq_records_log.append({
                            "partition": p,
                            "offset": m["offset"],
                            "reason": f"EXCEEDED_MAX_ATTEMPTS_{max_delivery_attempts}"
                        })
                        if m["offset"] == committed_offsets[p]:
                            committed_offsets[p] += 1
                            
                    if accum_time > max_poll_interval_ms:
                        break
                        
                duplicate_processed_count += max(0, processed_in_batch - 1)
                break
            else:
                for p, m in batch:
                    key = (p, m["offset"])
                    message_attempts[key] = message_attempts.get(key, 0) + 1
                    processed_records_log.append({
                        "consumer": c,
                        "partition": p,
                        "offset": m["offset"],
                        "status": "COMMITTED",
                        "attempt": message_attempts[key]
                    })
                    committed_offsets[p] = max(committed_offsets[p], m["offset"] + 1)
                    
        if rebalance_triggered:
            if assignor == "EAGER":
                total_stw_freeze_ms += rebalance_duration_ms
            else:
                total_stw_freeze_ms += (rebalance_duration_ms // 4)
                
            current_assignment = assign_partitions(active_consumers)
            
    completed_unique = sum(committed_offsets[p] for p in range(num_partitions)) - len(dlq_records_log)
    dlq_count = len(dlq_records_log)
    
    if total_messages == 0:
        verdict = "NO_MESSAGES"
    elif max_poll_interval_violations >= 2:
        verdict = "REBALANCE_CASCADE_STORM_DATA_DUPLICATION"
    elif max_poll_interval_violations == 1 and assignor == "COOPERATIVE_STICKY":
        verdict = "COOPERATIVE_STICKY_RESILIENT"
    elif max_poll_interval_violations == 1:
        verdict = "POISON_PILL_SINGLE_REBALANCE"
    elif rebalance_events_count == 0:
        verdict = "CLEAN_HIGH_THROUGHPUT"
    else:
        verdict = "REBALANCE_RESOLVED"
        
    summary = {
        "num_partitions": num_partitions,
        "consumers": consumers,
        "assignor": assignor,
        "max_poll_records": max_poll_records,
        "max_poll_interval_ms": max_poll_interval_ms,
        "max_delivery_attempts": max_delivery_attempts,
        "total_messages": total_messages,
        "unique_messages_completed": completed_unique,
        "dlq_messages_count": dlq_count,
        "duplicate_processed_count": duplicate_processed_count,
        "max_poll_interval_violations": max_poll_interval_violations,
        "rebalance_events_count": rebalance_events_count,
        "total_stw_freeze_ms": total_stw_freeze_ms,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "sample_records": processed_records_log[:10]
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            sys.exit(0)
        input_data = json.loads(raw_input)
        result = solve(input_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
