import json
import math
import sys

def solve(input_data):
    strategy = input_data.get("strategy", "XFETCH")
    initial_ttl_ms = int(input_data.get("initial_ttl_ms", 60000))
    compute_cost_ms = int(input_data.get("compute_cost_ms", 200))
    beta = float(input_data.get("beta", 1.0))
    db_capacity = int(input_data.get("db_capacity", 10))
    requests = sorted(input_data.get("requests", []), key=lambda r: r["time_ms"])

    cache_versions = [
        {"available_from": 0, "expiry": initial_ttl_ms, "value": "VALUE_V1", "delta": compute_cost_ms}
    ]

    in_flight_queries = []
    mutex_locked_until = 0

    total_requests = len(requests)
    cache_hits = 0
    cache_misses = 0
    early_recomputations = 0
    db_queries_total = 0
    max_concurrent_db = 0
    db_overload_errors = 0
    total_latency_ms = 0
    max_latency_ms = 0

    version_counter = 1
    request_results = []

    for req in requests:
        t = req["time_ms"]
        rid = req["req_id"]
        u = float(req.get("random_val", 0.5))

        active_queries = [q for q in in_flight_queries if q["start_t"] <= t < q["finish_t"]]
        has_in_flight = len(active_queries) > 0

        available_caches = [c for c in cache_versions if c["available_from"] <= t]
        latest_cache = available_caches[-1] if available_caches else None

        is_fresh = (latest_cache is not None and t < latest_cache["expiry"])

        status = "CACHE_HIT"
        latency = 1
        served_value = None

        if strategy == "NAIVE":
            if is_fresh:
                cache_hits += 1
                served_value = latest_cache["value"]
                latency = 1
                status = "CACHE_HIT"
            else:
                cache_misses += 1
                curr_concurrency = len(active_queries) + 1
                max_concurrent_db = max(max_concurrent_db, curr_concurrency)

                if curr_concurrency > db_capacity:
                    db_overload_errors += 1
                    status = "DB_OVERLOAD_503"
                    latency = 5000
                    served_value = None
                else:
                    db_queries_total += 1
                    status = "CACHE_MISS_STAMPEDE"
                    latency = compute_cost_ms
                    finish_t = t + compute_cost_ms
                    version_counter += 1
                    new_val = f"VALUE_V{version_counter}"
                    new_exp = finish_t + initial_ttl_ms
                    in_flight_queries.append({
                        "start_t": t,
                        "finish_t": finish_t,
                        "new_version_value": new_val,
                        "new_expiry": new_exp
                    })
                    cache_versions.append({
                        "available_from": finish_t,
                        "expiry": new_exp,
                        "value": new_val,
                        "delta": compute_cost_ms
                    })
                    served_value = new_val

        elif strategy == "MUTEX_LOCK":
            if is_fresh:
                cache_hits += 1
                served_value = latest_cache["value"]
                latency = 1
                status = "CACHE_HIT"
            else:
                cache_misses += 1
                if t >= mutex_locked_until:
                    status = "LOCK_ACQUIRED_LEADER"
                    db_queries_total += 1
                    latency = compute_cost_ms
                    finish_t = t + compute_cost_ms
                    mutex_locked_until = finish_t
                    version_counter += 1
                    new_val = f"VALUE_V{version_counter}"
                    new_exp = finish_t + initial_ttl_ms
                    cache_versions.append({
                        "available_from": finish_t,
                        "expiry": new_exp,
                        "value": new_val,
                        "delta": compute_cost_ms
                    })
                    served_value = new_val
                else:
                    status = "LOCK_WAIT_QUEUED"
                    wait_time = mutex_locked_until - t
                    latency = max(1, wait_time)
                    served_value = f"VALUE_V{version_counter}"

        elif strategy == "XFETCH":
            if is_fresh:
                time_to_expiry = latest_cache["expiry"] - t
                should_early = False
                if u > 0:
                    threshold = -beta * latest_cache["delta"] * math.log(u)
                    if threshold > time_to_expiry:
                        should_early = True

                if should_early and not has_in_flight:
                    early_recomputations += 1
                    db_queries_total += 1
                    status = "XFETCH_EARLY_RECOMPUTE"
                    finish_t = t + compute_cost_ms
                    version_counter += 1
                    new_val = f"VALUE_V{version_counter}"
                    new_exp = finish_t + initial_ttl_ms
                    in_flight_queries.append({
                        "start_t": t,
                        "finish_t": finish_t,
                        "new_version_value": new_val,
                        "new_expiry": new_exp
                    })
                    cache_versions.append({
                        "available_from": finish_t,
                        "expiry": new_exp,
                        "value": new_val,
                        "delta": compute_cost_ms
                    })
                    served_value = latest_cache["value"]
                    latency = 1
                    cache_hits += 1
                else:
                    status = "CACHE_HIT"
                    served_value = latest_cache["value"]
                    latency = 1
                    cache_hits += 1

            elif has_in_flight:
                status = "CACHE_HIT_STALE_REVALIDATING"
                served_value = latest_cache["value"]
                latency = 1
                cache_hits += 1

            else:
                cache_misses += 1
                status = "CACHE_MISS"
                db_queries_total += 1
                latency = compute_cost_ms
                finish_t = t + compute_cost_ms
                version_counter += 1
                new_val = f"VALUE_V{version_counter}"
                new_exp = finish_t + initial_ttl_ms
                in_flight_queries.append({
                    "start_t": t,
                    "finish_t": finish_t,
                    "new_version_value": new_val,
                    "new_expiry": new_exp
                })
                cache_versions.append({
                    "available_from": finish_t,
                    "expiry": new_exp,
                    "value": new_val,
                    "delta": compute_cost_ms
                })
                served_value = new_val

        total_latency_ms += latency
        max_latency_ms = max(max_latency_ms, latency)
        request_results.append({
            "req_id": rid,
            "status": status,
            "served_value": served_value,
            "latency_ms": latency
        })

    avg_latency = round(total_latency_ms / total_requests, 2) if total_requests > 0 else 0.0

    if strategy == "NAIVE":
        if db_overload_errors > 0:
            diag = f"CRITICAL: Cache Stampede disaster! {cache_misses} concurrent misses flooded DB with {db_queries_total} queries, causing {db_overload_errors} DB overload failures (max concurrency {max_concurrent_db})."
        else:
            diag = f"WARNING: Cache stampede occurred with {db_queries_total} concurrent DB queries during TTL expiration."
    elif strategy == "MUTEX_LOCK":
        diag = f"MUTEX_LOCK protected DB ({db_queries_total} queries), but caused latency spike (max {max_latency_ms}ms, avg {avg_latency}ms) due to thread lock contention."
    else: # XFETCH
        diag = f"OPTIMAL: XFetch probabilistic early expiration eliminated cache stampede! Cache hits {cache_hits}/{total_requests}, early recomputations {early_recomputations}, 0 DB overloads, avg latency {avg_latency}ms."

    return {
        "strategy": strategy,
        "metrics": {
            "total_requests": total_requests,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "early_recomputations": early_recomputations,
            "db_queries_total": db_queries_total,
            "max_concurrent_db_queries": max_concurrent_db,
            "db_overload_errors": db_overload_errors,
            "avg_latency_ms": avg_latency,
            "max_latency_ms": max_latency_ms
        },
        "requests": request_results,
        "diagnosis": diag
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
