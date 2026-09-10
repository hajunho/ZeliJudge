import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def calc_percentile(sorted_list, pct):
    if not sorted_list:
        return 0.0
    idx = max(0, min(len(sorted_list) - 1, math.ceil(pct / 100.0 * len(sorted_list)) - 1))
    return sorted_list[idx]

def simulate_rocksdb_writethread(input_data: dict) -> dict:
    config = input_data["config"]
    requests = input_data["requests"]

    enable_pipelined = config.get("enable_pipelined_write", True)
    allow_concurrent_memtable = config.get("allow_concurrent_memtable_write", True)
    max_batch_group_bytes = config.get("max_batch_group_bytes", 1048576)
    max_batch_group_count = config.get("max_batch_group_count", 64)
    memtable_capacity_bytes = config.get("memtable_capacity_bytes", 67108864)
    batch_window_us = config.get("batch_window_us", 2.0)

    cost_queue_overhead_us = config.get("cost_queue_overhead_us", 0.5)
    cost_wal_write_per_byte_us = config.get("cost_wal_write_per_byte_us", 0.0001)
    cost_wal_fsync_us = config.get("cost_wal_fsync_us", 50.0)
    cost_memtable_insert_per_key_us = config.get("cost_memtable_insert_per_key_us", 0.8)

    current_seq = config.get("initial_sequence_number", 1000)
    current_memtable_usage = config.get("initial_memtable_usage_bytes", 0)

    sorted_requests = sorted(requests, key=lambda x: (x["arrival_time_us"], x["id"]))

    batch_groups = []
    thread_results = {}
    stalls = 0
    total_wal_bytes = 0

    idx = 0
    n = len(sorted_requests)

    while idx < n:
        leader_req = sorted_requests[idx]
        group_arrival_time = leader_req["arrival_time_us"]

        if current_memtable_usage >= memtable_capacity_bytes:
            stalls += 1
            thread_results[leader_req["id"]] = {
                "id": leader_req["id"],
                "group_id": None,
                "role": "LEADER",
                "status": "WRITE_STALL_MEMTABLE_FULL",
                "batch_keys_count": len(leader_req.get("batch", [])),
                "sequence_range": None,
                "latency_us": 0.0
            }
            idx += 1
            continue

        group = [leader_req]
        group_bytes = sum(len(m["key"]) + len(m.get("value", "")) for m in leader_req["batch"])
        has_sync = leader_req.get("sync", False)

        next_idx = idx + 1
        while next_idx < n:
            cand = sorted_requests[next_idx]
            cand_bytes = sum(len(m["key"]) + len(m.get("value", "")) for m in cand["batch"])
            if cand["arrival_time_us"] - group_arrival_time <= batch_window_us:
                if len(group) < max_batch_group_count and group_bytes + cand_bytes <= max_batch_group_bytes:
                    group.append(cand)
                    group_bytes += cand_bytes
                    if cand.get("sync", False):
                        has_sync = True
                    next_idx += 1
                else:
                    break
            else:
                break

        group_id = f"GROUP_{len(batch_groups) + 1:03d}"
        leader_id = leader_req["id"]
        followers = [r["id"] for r in group[1:]]

        total_keys = sum(len(r["batch"]) for r in group)
        start_seq = current_seq
        end_seq = current_seq + total_keys - 1
        current_seq = end_seq + 1

        wal_write_time = group_bytes * cost_wal_write_per_byte_us
        if has_sync:
            wal_write_time += cost_wal_fsync_us

        total_wal_bytes += group_bytes
        current_memtable_usage += group_bytes

        if enable_pipelined and allow_concurrent_memtable:
            max_keys_in_thread = max(len(r["batch"]) for r in group)
            memtable_wall_clock = max_keys_in_thread * cost_memtable_insert_per_key_us
            pipelined_overlap = True
        else:
            memtable_wall_clock = total_keys * cost_memtable_insert_per_key_us
            pipelined_overlap = False

        group_total_latency = cost_queue_overhead_us + wal_write_time + memtable_wall_clock

        thread_seq_counter = start_seq
        for r in group:
            rid = r["id"]
            is_leader = (rid == leader_id)
            r_keys = len(r["batch"])
            t_start_seq = thread_seq_counter
            t_end_seq = thread_seq_counter + r_keys - 1
            thread_seq_counter = t_end_seq + 1

            if enable_pipelined and allow_concurrent_memtable:
                r_memtable_time = r_keys * cost_memtable_insert_per_key_us
                r_latency = cost_queue_overhead_us + wal_write_time + r_memtable_time
            else:
                r_latency = group_total_latency

            thread_results[rid] = {
                "id": rid,
                "group_id": group_id,
                "role": "LEADER" if is_leader else "FOLLOWER",
                "status": "OK",
                "batch_keys_count": r_keys,
                "sequence_range": [t_start_seq, t_end_seq] if r_keys > 0 else None,
                "latency_us": round(r_latency, 2)
            }

        batch_groups.append({
            "group_id": group_id,
            "leader_id": leader_id,
            "followers_count": len(followers),
            "total_writers": len(group),
            "total_bytes": group_bytes,
            "total_keys": total_keys,
            "sequence_range": [start_seq, end_seq],
            "has_sync": has_sync,
            "pipelined_parallel": pipelined_overlap,
            "group_latency_us": round(group_total_latency, 2)
        })

        idx = next_idx

    ok_latencies = [t["latency_us"] for t in thread_results.values() if t["status"] == "OK"]
    sorted_lats = sorted(ok_latencies)
    avg_lat = round(sum(ok_latencies) / len(ok_latencies), 2) if ok_latencies else 0.0
    p50_lat = round(calc_percentile(sorted_lats, 50), 2)
    p99_lat = round(calc_percentile(sorted_lats, 99), 2)
    max_lat = round(sorted_lats[-1], 2) if sorted_lats else 0.0

    return {
        "summary": {
            "total_requests": len(requests),
            "total_batch_groups": len(batch_groups),
            "avg_writers_per_group": round(len(requests) / len(batch_groups), 2) if batch_groups else 0.0,
            "total_wal_bytes": total_wal_bytes,
            "final_sequence_number": current_seq - 1,
            "final_memtable_usage_bytes": current_memtable_usage,
            "stalls_count": stalls,
            "avg_latency_us": avg_lat,
            "p50_latency_us": p50_lat,
            "p99_latency_us": p99_lat,
            "max_latency_us": max_lat
        },
        "batch_groups": batch_groups,
        "thread_results": [thread_results[r["id"]] for r in sorted_requests if r["id"] in thread_results]
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = simulate_rocksdb_writethread(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
