import json
import sys

def simulate_mvcc_gc(data):
    cfg = data["cluster_config"]
    gc_life_time_sec = cfg.get("gc_life_time_sec", 600)
    max_txn_time_sec = cfg.get("max_txn_time_sec", 300)
    kill_lagging_txns = cfg.get("kill_lagging_txns", False)
    gc_mode = cfg.get("gc_mode", "LEGACY_RANGEDEL")
    max_scan_amp = cfg.get("max_scan_amplification", 100)
    enable_seek_bounds = cfg.get("enable_seek_bounds", False)

    # Initial Storage State: key -> list of versions sorted by commit_ts desc
    kv_store = {}
    for item in data.get("initial_kv_versions", []):
        k = item["key"]
        if k not in kv_store:
            kv_store[k] = []
        kv_store[k].append({
            "commit_ts": item["commit_ts"],
            "is_delete": item.get("is_delete", False),
            "val": item.get("val", "")
        })
    for k in kv_store:
        kv_store[k].sort(key=lambda v: v["commit_ts"], reverse=True)

    # Active Txns
    active_txns = {}
    for t in data.get("initial_active_txns", []):
        active_txns[t["txn_id"]] = {
            "txn_id": t["txn_id"],
            "name": t["name"],
            "start_ts": t["start_ts"]
        }

    # CDC Feeds
    cdc_feeds = {}
    for c in data.get("initial_cdc_feeds", []):
        cdc_feeds[c["feed_id"]] = c["checkpoint_ts"]

    current_ts = data.get("initial_ts", 1000)
    safe_point_ts = data.get("initial_safe_point_ts", 0)

    # Metrics
    total_tombstones_scanned = 0
    query_timeouts = 0
    lsm_write_stalls = 0
    gc_runs = 0
    obsolete_versions_purged = 0
    stalled_by_txn = False
    stalled_by_cdc = False
    timed_out_queries = []

    def compute_safe_point():
        nonlocal safe_point_ts, stalled_by_txn, stalled_by_cdc
        candidate = current_ts - gc_life_time_sec
        if candidate <= safe_point_ts:
            return safe_point_ts

        # Active txns check
        min_txn_ts = None
        for tid, t in list(active_txns.items()):
            dur = current_ts - t["start_ts"]
            if dur > max_txn_time_sec:
                if kill_lagging_txns:
                    del active_txns[tid]
                    continue
            if min_txn_ts is None or t["start_ts"] < min_txn_ts:
                min_txn_ts = t["start_ts"]

        # CDC feeds check
        min_cdc_ts = None
        for fid, cts in cdc_feeds.items():
            if min_cdc_ts is None or cts < min_cdc_ts:
                min_cdc_ts = cts

        effective_limit = candidate
        blocked_by_t = False
        blocked_by_c = False

        if min_txn_ts is not None and min_txn_ts < effective_limit:
            effective_limit = min_txn_ts
            blocked_by_t = True

        if min_cdc_ts is not None and min_cdc_ts < effective_limit:
            effective_limit = min_cdc_ts
            blocked_by_c = True

        new_safe_point = max(safe_point_ts, effective_limit)
        if candidate > new_safe_point:
            if blocked_by_t:
                stalled_by_txn = True
            elif blocked_by_c:
                stalled_by_cdc = True

        safe_point_ts = new_safe_point
        return safe_point_ts

    def run_gc():
        nonlocal obsolete_versions_purged, lsm_write_stalls, gc_runs
        gc_runs += 1
        sp = compute_safe_point()
        purged_this_run = 0

        for k, versions in list(kv_store.items()):
            new_versions = []
            seen_latest_at_sp = False
            for v in versions:
                if v["commit_ts"] > sp:
                    new_versions.append(v)
                else:
                    if not seen_latest_at_sp:
                        seen_latest_at_sp = True
                        if not v["is_delete"]:
                            new_versions.append(v)
                        else:
                            purged_this_run += 1
                    else:
                        purged_this_run += 1
            kv_store[k] = new_versions

        obsolete_versions_purged += purged_this_run
        if gc_mode == "LEGACY_RANGEDEL":
            if purged_this_run >= 10000:
                lsm_write_stalls += 1

    events = sorted(data.get("events", []), key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]
        current_ts = ev.get("time_sec", current_ts)

        if ev_type == "ADVANCE_TIME":
            current_ts = ev["new_ts"]

        elif ev_type == "TXN_START":
            active_txns[ev["txn_id"]] = {
                "txn_id": ev["txn_id"],
                "name": ev["name"],
                "start_ts": ev["start_ts"]
            }

        elif ev_type == "TXN_COMMIT":
            tid = ev["txn_id"]
            if tid in active_txns:
                del active_txns[tid]
            for w in ev.get("writes", []):
                k = w["key"]
                if k not in kv_store:
                    kv_store[k] = []
                kv_store[k].append({
                    "commit_ts": w["commit_ts"],
                    "is_delete": w.get("is_delete", False),
                    "val": w.get("val", "")
                })
                kv_store[k].sort(key=lambda v: v["commit_ts"], reverse=True)

        elif ev_type == "TXN_ABORT":
            tid = ev["txn_id"]
            if tid in active_txns:
                del active_txns[tid]

        elif ev_type == "CDC_CHECKPOINT_UPDATE":
            cdc_feeds[ev["feed_id"]] = ev["checkpoint_ts"]

        elif ev_type == "TRIGGER_GC":
            run_gc()

        elif ev_type == "RANGE_SCAN":
            qid = ev["query_id"]
            start_k = ev["start_key"]
            end_k = ev["end_key"]
            read_ts = ev["read_ts"]
            limit = ev.get("limit", 1000)

            matched_keys = [k for k in sorted(kv_store.keys()) if start_k <= k <= end_k]
            valid_results = 0
            tombstones_scanned = 0
            keys_evaluated = 0

            for k in matched_keys:
                if valid_results >= limit:
                    break
                versions = kv_store[k]
                found_visible = False
                for v in versions:
                    keys_evaluated += 1
                    if v["commit_ts"] <= read_ts:
                        if not v["is_delete"]:
                            valid_results += 1
                            found_visible = True
                        else:
                            tombstones_scanned += 1
                        break
                    else:
                        tombstones_scanned += 1

            total_tombstones_scanned += tombstones_scanned
            denom = max(1, valid_results)
            amp = keys_evaluated / denom
            if enable_seek_bounds:
                amp = min(amp, 20.0)

            if amp > max_scan_amp or tombstones_scanned > 5000:
                query_timeouts += 1
                timed_out_queries.append(qid)

    # Diagnosis Hierarchy
    if query_timeouts > 0:
        root_cause = "RANGE_SCAN_TIMEOUT_DUE_TO_TOMBSTONE_AMPLIFICATION"
    elif lsm_write_stalls > 0:
        root_cause = "LSM_WRITE_STALL_DUE_TO_MASSIVE_TOMBSTONE_PURGE"
    elif stalled_by_txn:
        root_cause = "GC_SAFEPOINT_STALLED_BY_LONG_RUNNING_TXN"
    elif stalled_by_cdc:
        root_cause = "GC_SAFEPOINT_STALLED_BY_LAGGING_CDC"
    else:
        root_cause = "HEALTHY_MVCC_GC_AND_SCAN_OPERATION"

    recommendations = []
    if gc_mode == "LEGACY_RANGEDEL":
        recommendations.append("ENABLE_ROCKSDB_COMPACTION_FILTER_GC")
    if not kill_lagging_txns:
        recommendations.append("ENFORCE_MAX_TXN_EXECUTION_TIME_LIMIT")
    if not enable_seek_bounds:
        recommendations.append("ENABLE_PREFIX_BLOOM_FILTER_AND_SEEK_BOUNDS")
    if stalled_by_cdc:
        recommendations.append("SET_CDC_MAX_STALENESS_AND_AUTO_PAUSE")

    if not recommendations:
        recommendations.append("MONITOR_MVCC_VERSION_COUNT_AND_SST_HEALTH")

    return {
        "final_state": {
            "current_ts": current_ts,
            "safe_point_ts": safe_point_ts,
            "active_txns_count": len(active_txns),
            "total_kv_keys": len(kv_store),
            "total_versions": sum(len(v) for v in kv_store.values())
        },
        "metrics": {
            "total_tombstones_scanned": total_tombstones_scanned,
            "query_timeouts": query_timeouts,
            "timed_out_queries": timed_out_queries,
            "lsm_write_stalls": lsm_write_stalls,
            "obsolete_versions_purged": obsolete_versions_purged
        },
        "root_cause": root_cause,
        "recommendations": recommendations
    }

def main():
    try:
        input_data = sys.stdin.read().strip()
        if not input_data:
            return
        data = json.loads(input_data)
        result = simulate_mvcc_gc(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
