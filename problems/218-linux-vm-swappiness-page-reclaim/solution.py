import sys
import json

def simulate_vm_reclaim(data):
    config = data.get("config", {})
    swappiness = int(config.get("swappiness", 60))
    total_ram_mb = float(config.get("total_ram_mb", 32768))
    swap_capacity_mb = float(config.get("swap_capacity_mb", 8192))
    swap_device = config.get("swap_device", "FAST_NVME")  # "SLOW_HDD", "FAST_NVME", "ZSWAP", "NONE"
    zswap_enabled = bool(config.get("zswap_enabled", False))
    mglru_enabled = bool(config.get("mglru_enabled", False))

    working_set_mb = float(config.get("working_set_mb", 12288))
    anon_mb = float(config.get("initial_anon_mb", 16384))
    file_cache_mb = float(config.get("initial_file_cache_mb", 14336))
    free_mb = max(0.0, total_ram_mb - anon_mb - file_cache_mb)

    swap_used_mb = 0.0
    zswap_used_mb = 0.0

    low_wmark_mb = total_ram_mb * 0.05
    high_wmark_mb = total_ram_mb * 0.08

    workload = data.get("workload", [])

    total_queries = 0
    total_cache_hits = 0
    total_disk_reads = 0
    total_reclaim_stall_ms = 0.0
    oom_killed = False

    for step in workload:
        alloc_anon = float(step.get("alloc_anon_mb", 0.0))
        queries = int(step.get("queries", 1000))
        total_queries += queries

        needed_free = alloc_anon + low_wmark_mb
        if free_mb < needed_free and not oom_killed:
            reclaim_target = (alloc_anon + high_wmark_mb) - free_mb

            if swap_capacity_mb <= 0 or swappiness == 0:
                anon_ratio = 0.0
                file_ratio = 1.0
            elif mglru_enabled:
                if file_cache_mb <= working_set_mb * 1.1:
                    anon_ratio = 0.8
                    file_ratio = 0.2
                else:
                    anon_ratio = 0.3
                    file_ratio = 0.7
            else:
                anon_ratio = swappiness / 200.0
                file_ratio = (200.0 - swappiness) / 200.0

            # 1. Reclaim from file cache
            target_file_reclaim = reclaim_target * file_ratio
            actual_file_reclaimed = min(file_cache_mb, target_file_reclaim)
            file_cache_mb -= actual_file_reclaimed
            free_mb += actual_file_reclaimed

            # 2. Reclaim from anon memory (swap out)
            target_anon_reclaim = reclaim_target * anon_ratio
            avail_swap = max(0.0, swap_capacity_mb - swap_used_mb)
            actual_anon_reclaimed = min(anon_mb * 0.6, target_anon_reclaim, avail_swap)

            if actual_anon_reclaimed > 0:
                anon_mb -= actual_anon_reclaimed
                swap_used_mb += actual_anon_reclaimed
                free_mb += actual_anon_reclaimed

                if swap_device == "SLOW_HDD":
                    total_reclaim_stall_ms += actual_anon_reclaimed * 2.5
                elif zswap_enabled:
                    zswap_used_mb += actual_anon_reclaimed / 3.0
                else:
                    total_reclaim_stall_ms += actual_anon_reclaimed * 0.05

            # 3. Emergency direct file cache eviction if still shortfall
            if free_mb < alloc_anon:
                shortfall = alloc_anon - free_mb
                emergency_file = min(file_cache_mb, shortfall)
                file_cache_mb -= emergency_file
                free_mb += emergency_file
                total_reclaim_stall_ms += emergency_file * 0.2

            if free_mb < alloc_anon:
                oom_killed = True
                total_reclaim_stall_ms += 10000.0
            else:
                anon_mb += alloc_anon
                free_mb -= alloc_anon

        elif not oom_killed:
            anon_mb += alloc_anon
            free_mb -= alloc_anon

        # Query execution against page cache
        if queries > 0:
            cached_fraction = min(1.0, file_cache_mb / working_set_mb) if working_set_mb > 0 else 1.0
            hits = int(queries * cached_fraction)
            misses = queries - hits
            total_cache_hits += hits
            total_disk_reads += misses

    hit_rate_pct = (total_cache_hits / total_queries * 100.0) if total_queries > 0 else 0.0
    disk_read_penalty_ms = 2.0
    query_latency_ms = 0.5 + ((total_disk_reads * disk_read_penalty_ms) / total_queries) if total_queries > 0 else 0.5

    if oom_killed:
        verdict = "OOM_KILLER_INVOCATION_STALL"
        status = "FAILED"
    elif hit_rate_pct < 55.0:
        verdict = "PAGE_CACHE_EVICTION_THRASHING"
        status = "FAILED"
    elif total_reclaim_stall_ms > 2000.0 and swap_device == "SLOW_HDD":
        verdict = "EXCESSIVE_SWAP_IO_LATENCY_SPIKE"
        status = "FAILED"
    elif mglru_enabled and hit_rate_pct >= 85.0:
        verdict = "OPTIMAL_CGROUP_V2_MGLRU_RECLAIM"
        status = "SUCCESS"
    elif hit_rate_pct >= 75.0 and total_reclaim_stall_ms < 500.0:
        verdict = "OPTIMAL_BALANCED_MEMORY_RECLAIM"
        status = "SUCCESS"
    else:
        verdict = "SUBOPTIMAL_MEMORY_PRESSURE"
        status = "SUCCESS"

    return {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "final_anon_mb": round(anon_mb, 1),
            "final_file_cache_mb": round(file_cache_mb, 1),
            "final_free_mb": round(free_mb, 1),
            "final_swap_used_mb": round(swap_used_mb, 1),
            "page_cache_hit_rate_pct": round(hit_rate_pct, 1),
            "total_disk_reads": total_disk_reads,
            "average_query_latency_ms": round(query_latency_ms, 2),
            "total_reclaim_stall_ms": round(total_reclaim_stall_ms, 1),
            "oom_killed": oom_killed
        }
    }

def main():
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return
    data = json.loads(raw_input)
    result = simulate_vm_reclaim(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
