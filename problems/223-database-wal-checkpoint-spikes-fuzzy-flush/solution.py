"""
Problem 223: Database Storage Engine: WAL Checkpoint Spikes, Sharp Checkpoint vs Fuzzy Spread Flush & Backend Writes Thrashing
"""
import sys
import json

def simulate_checkpoint(data):
    config = data.get("config", {})
    checkpoint_type = config.get("checkpoint_type", "FUZZY")
    timeout_sec = float(config.get("checkpoint_timeout_sec", 300.0))
    completion_target = float(config.get("checkpoint_completion_target", 0.9 if checkpoint_type == "FUZZY" else 0.1))
    max_wal_mb = float(config.get("max_wal_size_mb", 4096.0))
    shared_buffers_mb = float(config.get("shared_buffers_mb", 2048.0))
    disk_max_bw_mbps = float(config.get("disk_max_write_bandwidth_mbps", 250.0))
    bgwriter_enabled = bool(config.get("bgwriter_enabled", True))
    bgwriter_rate = float(config.get("bgwriter_lru_rate_mbps", 20.0)) if bgwriter_enabled else 0.0

    workload = data.get("workload", {})
    duration_sec = float(workload.get("duration_sec", 300.0))
    dirty_rate_mbps = float(workload.get("dirty_page_generation_rate_mbps", 30.0))
    wal_rate_mbps = float(workload.get("wal_generation_rate_mbps", 25.0))
    query_qps = float(workload.get("incoming_query_rate_qps", 2000.0))

    time_to_wal_checkpoint = (max_wal_mb / wal_rate_mbps) if wal_rate_mbps > 0 else float("inf")
    is_wal_driven = time_to_wal_checkpoint < timeout_sec
    actual_interval_sec = min(timeout_sec, time_to_wal_checkpoint)

    if checkpoint_type == "SHARP" or completion_target <= 0.2:
        peak_disk_utilization = 1.0
        backend_writes_mb = 0.0
        p99_query_latency_ms = 4500.0
    else:
        target_flush_sec = actual_interval_sec * completion_target
        target_flush_sec = max(1.0, target_flush_sec)

        dirty_accumulated = dirty_rate_mbps * actual_interval_sec
        desired_chkp_rate = dirty_accumulated / target_flush_sec

        chkp_rate = min(disk_max_bw_mbps, desired_chkp_rate)
        total_clean_rate = min(disk_max_bw_mbps, chkp_rate + bgwriter_rate)

        peak_disk_utilization = min(1.0, total_clean_rate / disk_max_bw_mbps) if disk_max_bw_mbps > 0 else 1.0

        clean_buffer_pool_mb = shared_buffers_mb * 0.35

        if dirty_rate_mbps > total_clean_rate:
            drain_speed = dirty_rate_mbps - total_clean_rate
            time_to_exhaust_sec = clean_buffer_pool_mb / drain_speed
            if time_to_exhaust_sec < actual_interval_sec:
                backend_write_duration = actual_interval_sec - time_to_exhaust_sec
                backend_writes_mb = drain_speed * backend_write_duration
                p99_query_latency_ms = 1850.0
            else:
                backend_writes_mb = 0.0
                p99_query_latency_ms = 12.0 + (peak_disk_utilization * 20.0)
        else:
            backend_writes_mb = 0.0
            p99_query_latency_ms = 3.5 + (peak_disk_utilization * 6.0)

    if peak_disk_utilization >= 0.98 and (checkpoint_type == "SHARP" or completion_target <= 0.2):
        status = "FAILED"
        verdict = "SHARP_CHECKPOINT_IO_SPIKE_STALL"
    elif backend_writes_mb > 0.0:
        status = "FAILED"
        verdict = "BACKEND_SYNC_FLUSH_THRASHING"
    elif is_wal_driven and actual_interval_sec < 45.0:
        status = "FAILED"
        verdict = "WAL_DRIVEN_UNSCHEDULED_CHECKPOINT_BURST"
    elif checkpoint_type == "FUZZY" and completion_target >= 0.8 and backend_writes_mb == 0.0 and peak_disk_utilization <= 0.65:
        status = "SUCCESS"
        verdict = "OPTIMAL_FUZZY_SPREAD_CHECKPOINT"
    else:
        status = "SUCCESS"
        verdict = "NORMAL_DATABASE_STEADY_STATE"

    return {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "checkpoint_type": checkpoint_type,
            "actual_checkpoint_interval_sec": round(actual_interval_sec, 2),
            "is_wal_driven": is_wal_driven,
            "peak_disk_utilization_ratio": round(peak_disk_utilization, 4),
            "backend_writes_mb": round(backend_writes_mb, 2),
            "p99_query_latency_ms": round(p99_query_latency_ms, 2)
        }
    }

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return
        data = json.loads(raw_input)
        result = simulate_checkpoint(data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
