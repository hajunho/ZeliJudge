import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    join_strategy = config.get("join_strategy", "INTERVAL_JOIN")
    interval_lower_ms = int(config.get("interval_lower_ms", -300000))
    interval_upper_ms = int(config.get("interval_upper_ms", 1800000))
    window_size_ms = int(config.get("window_size_ms", 600000))
    watermark_idleness_enabled = bool(config.get("watermark_idleness_enabled", False))
    state_ttl_ms = config.get("state_ttl_ms", None)
    if state_ttl_ms is not None:
        state_ttl_ms = int(state_ttl_ms)
    max_state_memory_mb = float(config.get("max_state_memory_mb", 2048.0))

    workload = data.get("workload", {})
    orders = workload.get("orders", [])
    payments = workload.get("payments", [])
    partitions_activity = workload.get("partitions_activity", {})

    orders_map = {o["id"]: o for o in orders}
    payments_map = {p["order_id"]: p for p in payments}

    true_matchable_count = 0
    for ord_id, o in orders_map.items():
        if ord_id in payments_map:
            p = payments_map[ord_id]
            diff = p["ts"] - o["ts"]
            if interval_lower_ms <= diff <= interval_upper_ms:
                true_matchable_count += 1

    joined_count = 0
    missed_joins = 0
    premature_evictions = 0
    peak_state_entries = 0
    watermark_stalled = False
    oom_occurred = False

    if join_strategy == "WINDOWED_JOIN":
        for ord_id, o in orders_map.items():
            if ord_id in payments_map:
                p = payments_map[ord_id]
                diff = p["ts"] - o["ts"]
                if interval_lower_ms <= diff <= interval_upper_ms:
                    w_o = o["ts"] // window_size_ms
                    w_p = p["ts"] // window_size_ms
                    if w_o == w_p:
                        joined_count += 1
                    else:
                        missed_joins += 1
        peak_state_entries = len(orders) // 2
        peak_state_mb = (peak_state_entries * 0.5) / 1024.0

    elif join_strategy == "INTERVAL_JOIN":
        has_idle_partition = any(status == "IDLE" or "IDLE" in status for status in partitions_activity.values())

        if has_idle_partition and not watermark_idleness_enabled:
            watermark_stalled = True
            peak_state_entries = len(orders) + len(payments)
            peak_state_mb = (peak_state_entries * 2.5) / 1024.0
            if peak_state_mb > max_state_memory_mb:
                oom_occurred = True
            joined_count = true_matchable_count
        else:
            watermark_stalled = False
            if state_ttl_ms is not None and state_ttl_ms < interval_upper_ms:
                for ord_id, o in orders_map.items():
                    if ord_id in payments_map:
                        p = payments_map[ord_id]
                        diff = p["ts"] - o["ts"]
                        if interval_lower_ms <= diff <= interval_upper_ms:
                            if diff > state_ttl_ms:
                                premature_evictions += 1
                                missed_joins += 1
                            else:
                                joined_count += 1
            else:
                joined_count = true_matchable_count

            concurrent_window_ratio = min(1.0, (interval_upper_ms - interval_lower_ms) / 3600000.0)
            peak_state_entries = int((len(orders) + len(payments)) * concurrent_window_ratio * 0.25)
            peak_state_entries = max(10, peak_state_entries)
            peak_state_mb = (peak_state_entries * 1.5) / 1024.0

    if oom_occurred:
        status = "FAILED"
        verdict = "WATERMARK_SKEW_STATE_TTL_STARVATION_OOM"
    elif premature_evictions > 0 and (missed_joins / max(1, true_matchable_count)) >= 0.1:
        status = "FAILED"
        verdict = "PREMATURE_STATE_EVICTION_DATA_LOSS"
    elif join_strategy == "WINDOWED_JOIN":
        if missed_joins > 0 and (missed_joins / max(1, true_matchable_count)) >= 0.15:
            status = "FAILED"
            verdict = "WINDOW_BOUNDARY_MISSED_JOIN_DATA_LOSS"
        else:
            status = "SUCCESS"
            verdict = "WINDOWED_JOIN_PERFECT_ALIGNMENT"
    elif watermark_stalled:
        status = "WARNING"
        verdict = "WATERMARK_STALLED_IDLE_PARTITION_LEAK"
    else:
        status = "SUCCESS"
        verdict = "OPTIMAL_INTERVAL_JOIN_WATERMARK_EVACUATION"

    join_success_rate = (joined_count / max(1, true_matchable_count)) if true_matchable_count > 0 else 1.0

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "join_strategy": join_strategy,
            "true_matchable_count": true_matchable_count,
            "joined_count": joined_count,
            "missed_joins": missed_joins,
            "join_success_rate": round(join_success_rate, 4),
            "peak_state_entries": peak_state_entries,
            "peak_state_mb": round(peak_state_mb, 2),
            "watermark_stalled": watermark_stalled,
            "oom_occurred": oom_occurred
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
