import sys
import json
from collections import deque

def simulate_vfs_dentry(data):
    config = data.get("config", {})
    mode = config.get("mode", "OPTIMAL_BLOOM_FILTER_VFS_GUARD")
    total_memory_mb = config.get("total_memory_mb", 1000)
    dentry_size_bytes = config.get("dentry_size_bytes", 20480)

    min_watermark_mb = config.get("min_watermark_mb", 80)
    vfs_cache_pressure = config.get("vfs_cache_pressure", 100)
    bloom_guard_enabled = ("BLOOM" in mode)

    existing_files = set(data.get("existing_files", []))
    requests = data.get("requests", [])

    app_memory_mb = config.get("initial_app_memory_mb", 600)
    page_cache_mb = config.get("initial_page_cache_mb", 300)
    slab_dentry_bytes = 0

    positive_dentries = {}
    negative_dentries = {}
    dentry_lru = deque()

    metrics = {
        "total_requests": len(requests),
        "existing_file_hits": 0,
        "negative_dentry_hits": 0,
        "negative_dentries_created": 0,
        "negative_dentries_reclaimed": 0,
        "bloom_filter_rejected_requests": 0,
        "peak_slab_memory_mb": 0.0,
        "direct_reclaim_events": 0,
        "shrinker_lock_contention_events": 0,
        "oom_killer_triggered": False,
        "average_lookup_latency_us": 0.0
    }

    latencies_us = []

    def get_free_memory_mb():
        slab_mb = slab_dentry_bytes / (1024 * 1024)
        used = app_memory_mb + page_cache_mb + slab_mb
        return max(0.0, total_memory_mb - used)

    for req in requests:
        path = req["path"]
        is_exist = path in existing_files
        req_latency_us = 1.0

        if bloom_guard_enabled:
            if not is_exist:
                metrics["bloom_filter_rejected_requests"] += 1
                latencies_us.append(0.2)
                continue

        if path in positive_dentries:
            metrics["existing_file_hits"] += 1
            latencies_us.append(req_latency_us)
        elif path in negative_dentries:
            metrics["negative_dentry_hits"] += 1
            latencies_us.append(req_latency_us)
        else:
            req_latency_us += 15.0

            if is_exist:
                positive_dentries[path] = True
                dentry_lru.append(path)
                slab_dentry_bytes += dentry_size_bytes
                metrics["existing_file_hits"] += 1
            else:
                negative_dentries[path] = True
                dentry_lru.append(path)
                slab_dentry_bytes += dentry_size_bytes
                metrics["negative_dentries_created"] += 1

            free_mem = get_free_memory_mb()
            slab_mb = slab_dentry_bytes / (1024 * 1024)
            if slab_mb > metrics["peak_slab_memory_mb"]:
                metrics["peak_slab_memory_mb"] = slab_mb

            if free_mem < min_watermark_mb:
                metrics["direct_reclaim_events"] += 1

                reclaim_target_count = int(20 * (vfs_cache_pressure / 100.0))

                if vfs_cache_pressure >= 300:
                    metrics["shrinker_lock_contention_events"] += 1
                    req_latency_us += 50.0

                reclaimed = 0
                while dentry_lru and reclaimed < reclaim_target_count:
                    candidate = dentry_lru.popleft()
                    if candidate in negative_dentries:
                        del negative_dentries[candidate]
                        slab_dentry_bytes -= dentry_size_bytes
                        reclaimed += 1
                        metrics["negative_dentries_reclaimed"] += 1
                    elif candidate in positive_dentries:
                        del positive_dentries[candidate]
                        slab_dentry_bytes -= dentry_size_bytes
                        reclaimed += 1

                free_after = get_free_memory_mb()
                if free_after < 10.0:
                    metrics["oom_killer_triggered"] = True

            latencies_us.append(req_latency_us)

    slab_final_mb = slab_dentry_bytes / (1024 * 1024)
    if slab_final_mb > metrics["peak_slab_memory_mb"]:
        metrics["peak_slab_memory_mb"] = slab_final_mb

    metrics["peak_slab_memory_mb"] = round(metrics["peak_slab_memory_mb"], 2)
    avg_lat = (sum(latencies_us) / len(latencies_us)) if latencies_us else 0.0
    metrics["average_lookup_latency_us"] = round(avg_lat, 2)

    if metrics["oom_killer_triggered"] or metrics["peak_slab_memory_mb"] >= 70.0:
        verdict = "NEGATIVE_DENTRY_SLAB_EXHAUSTION_OOM"
        status = "FAILED"
    elif metrics["shrinker_lock_contention_events"] >= 15 or metrics["average_lookup_latency_us"] >= 25.0:
        verdict = "SHRINKER_LOCK_CONTENTION_CPU_STALL"
        status = "FAILED"
    elif bloom_guard_enabled:
        verdict = "OPTIMAL_BLOOM_FILTER_VFS_GUARD"
        status = "SUCCESS"
    else:
        verdict = "NORMAL_VFS_OPERATION"
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
    result = simulate_vfs_dentry(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
