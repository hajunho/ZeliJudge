import sys
import json
import heapq
from collections import defaultdict

def simulate_cache_consistency(data):
    config = data.get("config", {})
    mode = config.get("mode", "TRANSACTIONAL_CDC_CACHE_INVALIDATION")
    cdc_delay_ms = config.get("cdc_delay_ms", 10.0)
    delayed_delete_wait_ms = config.get("delayed_delete_wait_ms", 100.0)
    db_read_latency_ms = config.get("db_read_latency_ms", 15.0)

    initial_db = data.get("initial_db", {})
    initial_cache = data.get("initial_cache", {})

    db = dict(initial_db)
    cache = {}
    for k, v in initial_cache.items():
        cache[k] = {"value": v, "version": 1, "set_time": 0.0}

    db_version = {k: 1 for k in db}

    events = sorted(data.get("events", []), key=lambda x: x["timestamp_ms"])

    metrics = {
        "total_read_requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "total_write_requests": 0,
        "db_updates_committed": 0,
        "cache_deletions_executed": 0,
        "stale_cache_reads": 0,
        "inconsistent_keys_at_end": [],
        "cache_hit_rate_pct": 0.0,
        "consistency_rate_pct": 0.0
    }

    pq = []
    counter = 0

    for ev in events:
        counter += 1
        ev_type = "CLIENT_READ" if ev["action"] == "READ" else "CLIENT_WRITE"
        heapq.heappush(pq, (ev["timestamp_ms"], 0, counter, ev_type, ev))

    while pq:
        current_time_ms, prio, _, ev_type, payload = heapq.heappop(pq)

        if ev_type == "CLIENT_READ":
            metrics["total_read_requests"] += 1
            key = payload["key"]
            if key in cache:
                metrics["cache_hits"] += 1
                cached_val = cache[key]["value"]
                current_db_val = db.get(key)
                if cached_val != current_db_val:
                    metrics["stale_cache_reads"] += 1
            else:
                metrics["cache_misses"] += 1
                db_val = db.get(key)
                curr_ver = db_version.get(key, 1)
                read_lat = payload.get("db_read_latency_ms", db_read_latency_ms)
                read_res = {
                    "key": key,
                    "read_value": db_val,
                    "read_version": curr_ver,
                    "read_started_time": current_time_ms
                }
                counter += 1
                heapq.heappush(pq, (current_time_ms + read_lat, 1, counter, "DB_READ_COMPLETE", read_res))

        elif ev_type == "DB_READ_COMPLETE":
            key = payload["key"]
            val = payload["read_value"]
            ver = payload["read_version"]
            if mode == "TRANSACTIONAL_CDC_CACHE_INVALIDATION":
                if db_version.get(key, 1) > ver:
                    pass
                else:
                    cache[key] = {"value": val, "version": ver, "set_time": current_time_ms}
            else:
                cache[key] = {"value": val, "version": ver, "set_time": current_time_ms}

        elif ev_type == "CLIENT_WRITE":
            metrics["total_write_requests"] += 1
            key = payload["key"]
            new_val = payload["new_value"]

            if mode == "NAIVE_CACHE_ASIDE_UPDATE":
                db[key] = new_val
                db_version[key] = db_version.get(key, 1) + 1
                metrics["db_updates_committed"] += 1

                if not payload.get("simulate_delete_failure", False):
                    if key in cache:
                        del cache[key]
                        metrics["cache_deletions_executed"] += 1

            elif mode == "DELAYED_DOUBLE_DELETE":
                if key in cache:
                    del cache[key]
                    metrics["cache_deletions_executed"] += 1

                db[key] = new_val
                db_version[key] = db_version.get(key, 1) + 1
                metrics["db_updates_committed"] += 1

                del_payload = {"key": key}
                counter += 1
                heapq.heappush(pq, (current_time_ms + delayed_delete_wait_ms, 1, counter, "DELAYED_DELETE", del_payload))

            elif mode == "TRANSACTIONAL_CDC_CACHE_INVALIDATION":
                db[key] = new_val
                new_ver = db_version.get(key, 1) + 1
                db_version[key] = new_ver
                metrics["db_updates_committed"] += 1

                cdc_payload = {"key": key, "version": new_ver}
                counter += 1
                heapq.heappush(pq, (current_time_ms + cdc_delay_ms, 1, counter, "CDC_INVALIDATE", cdc_payload))

        elif ev_type == "DELAYED_DELETE":
            key = payload["key"]
            if key in cache:
                del cache[key]
                metrics["cache_deletions_executed"] += 1

        elif ev_type == "CDC_INVALIDATE":
            key = payload["key"]
            ver = payload["version"]
            if key in cache:
                if cache[key]["version"] <= ver:
                    del cache[key]
                    metrics["cache_deletions_executed"] += 1

    inconsistent_keys = []
    for k in db:
        if k in cache:
            if cache[k]["value"] != db[k]:
                inconsistent_keys.append(k)

    metrics["inconsistent_keys_at_end"] = sorted(inconsistent_keys)
    total_reads = metrics["total_read_requests"]
    hit_rate = (metrics["cache_hits"] / total_reads * 100.0) if total_reads > 0 else 0.0
    metrics["cache_hit_rate_pct"] = round(hit_rate, 2)

    consistent_reads = total_reads - metrics["stale_cache_reads"]
    cons_rate = (consistent_reads / total_reads * 100.0) if total_reads > 0 else 100.0
    metrics["consistency_rate_pct"] = round(cons_rate, 2)

    if len(metrics["inconsistent_keys_at_end"]) > 0 or metrics["stale_cache_reads"] > 0:
        if mode == "NAIVE_CACHE_ASIDE_UPDATE":
            verdict = "CACHE_INCONSISTENCY_STALE_DATA_DETECTED"
            status = "FAILED"
        elif mode == "DELAYED_DOUBLE_DELETE":
            if len(metrics["inconsistent_keys_at_end"]) == 0:
                verdict = "DELAYED_DOUBLE_DELETE_EVENTUAL_CONSISTENCY"
                status = "SUCCESS"
            else:
                verdict = "CACHE_INCONSISTENCY_STALE_DATA_DETECTED"
                status = "FAILED"
        else:
            verdict = "CACHE_INCONSISTENCY_STALE_DATA_DETECTED"
            status = "FAILED"
    else:
        if mode == "TRANSACTIONAL_CDC_CACHE_INVALIDATION":
            verdict = "OPTIMAL_TRANSACTIONAL_CDC_CONSISTENCY"
            status = "SUCCESS"
        else:
            verdict = "CLEAN_CACHE_CONSISTENCY"
            status = "SUCCESS"

    return {
        "status": status,
        "verdict": verdict,
        "mode": mode,
        "metrics": metrics
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_cache_consistency(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
