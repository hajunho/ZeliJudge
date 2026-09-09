import json
import sys

def simulate_balloon(data):
    vm_cfg = data["vm_config"]
    total_ram = vm_cfg["total_ram_mb"]
    thp_enabled = vm_cfg.get("thp_enabled", False)
    deflate_on_oom = vm_cfg.get("deflate_on_oom", False)
    granularity = vm_cfg.get("balloon_granularity", "4KB")
    guest_swap_total = vm_cfg.get("guest_swap_mb", 0)
    swappiness = vm_cfg.get("swappiness", 60)
    min_free_kbytes_mb = vm_cfg.get("min_free_kbytes_mb", 128)
    max_inflation_rate = vm_cfg.get("max_inflation_rate_mb_per_sec", 0)  # 0 = unlimited

    # Processes: pid -> dict
    processes = {}
    for p in data["processes"]:
        processes[p["pid"]] = {
            "pid": p["pid"],
            "name": p["name"],
            "rss_mb": p["rss_mb"],
            "oom_score_adj": p.get("oom_score_adj", 0),
            "thp_mb": p.get("thp_mb", 0),
            "killed": False
        }

    init = data["initial_state"]
    balloon_inflated = init["balloon_inflated_mb"]
    page_cache = init["page_cache_mb"]
    dirty_cache = init["dirty_cache_mb"]
    free_ram = init["free_ram_mb"]
    guest_swap_used = init.get("guest_swap_used_mb", 0)

    host_free_ram = init.get("host_free_ram_mb", 4096)
    host_swap_used = init.get("host_swap_used_mb", 0)

    # State tracking
    direct_reclaim_stalls = 0
    oom_killed_pids = []
    shattered_thp_count = 0  # each 2MB page
    double_swapping_detected = False

    def get_clean_cache():
        return max(0, page_cache - dirty_cache)

    def calc_oom_score(p):
        if p["oom_score_adj"] == -1000:
            return -1000
        score = int(p["rss_mb"] * 1000 / total_ram) + p["oom_score_adj"]
        return max(0, min(1000, score))

    def trigger_oom_kill():
        nonlocal free_ram
        alive = [p for p in processes.values() if not p["killed"]]
        if not alive:
            return None
        alive.sort(key=lambda p: (calc_oom_score(p), p["pid"]), reverse=True)
        victim = alive[0]
        if calc_oom_score(victim) < 0:
            return None  # unkillable
        victim["killed"] = True
        freed = victim["rss_mb"]
        free_ram += freed
        oom_killed_pids.append(victim["pid"])
        return victim

    def allocate_memory(amount_mb, is_balloon=False):
        nonlocal free_ram, page_cache, dirty_cache, balloon_inflated, guest_swap_used
        nonlocal direct_reclaim_stalls, shattered_thp_count, double_swapping_detected, host_swap_used

        needed = amount_mb
        # 1. Take from free_ram above min_free_kbytes_mb
        usable_free = max(0, free_ram - min_free_kbytes_mb)
        from_free = min(needed, usable_free)
        free_ram -= from_free
        needed -= from_free

        # 2. Reclaim clean page cache
        if needed > 0:
            clean = get_clean_cache()
            from_cache = min(needed, clean)
            page_cache -= from_cache
            needed -= from_cache
            if from_cache >= 512 or needed > 0:
                direct_reclaim_stalls += 1

        # 3. Swap out to guest swap if enabled
        if needed > 0 and guest_swap_total > 0 and swappiness > 0:
            swap_free = guest_swap_total - guest_swap_used
            if swap_free > 0:
                from_swap = min(needed, swap_free)
                guest_swap_used += from_swap
                needed -= from_swap
                direct_reclaim_stalls += 1
                if host_swap_used > 0:
                    double_swapping_detected = True

        # 4. Balloon auto-deflate if deflate_on_oom is active and process allocation
        if needed > 0 and not is_balloon and deflate_on_oom and balloon_inflated > 0:
            from_balloon = min(needed, balloon_inflated)
            balloon_inflated -= from_balloon
            free_ram += from_balloon
            needed -= from_balloon

        # 5. Out of Memory handling
        while needed > 0:
            victim = trigger_oom_kill()
            if not victim:
                break
            from_victim = min(needed, free_ram)
            free_ram -= from_victim
            needed -= from_victim

        # THP shattering check for 4KB balloon allocation
        if is_balloon and granularity == "4KB" and thp_enabled:
            shattered_mb = min(amount_mb, sum(p["thp_mb"] for p in processes.values() if not p["killed"]))
            shattered_2mb_pages = shattered_mb // 2
            shattered_thp_count = max(shattered_thp_count, shattered_2mb_pages)

        return (needed == 0)

    # Process events in order
    events = sorted(data["events"], key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]
        if ev_type == "BALLOON_TARGET_UPDATE":
            target = ev["target_balloon_mb"]
            delta = target - balloon_inflated
            if delta > 0:
                if max_inflation_rate > 0 and delta > max_inflation_rate:
                    direct_reclaim_stalls += 1
                success = allocate_memory(delta, is_balloon=True)
                if success or free_ram >= 0:
                    balloon_inflated += delta
                    host_free_ram += delta
            elif delta < 0:
                shrink = abs(delta)
                balloon_inflated -= shrink
                free_ram += shrink
                host_free_ram = max(0, host_free_ram - shrink)

        elif ev_type == "PROCESS_ALLOC_BURST":
            pid = ev["pid"]
            alloc_mb = ev["alloc_mb"]
            p = processes.get(pid)
            if p and not p["killed"]:
                success = allocate_memory(alloc_mb, is_balloon=False)
                if success:
                    p["rss_mb"] += alloc_mb
                    if thp_enabled and ev.get("is_thp", True):
                        p["thp_mb"] += alloc_mb

        elif ev_type == "HOST_MEMORY_PRESSURE":
            needed_reclaim = ev["host_reclaim_needed_mb"]
            if host_free_ram < needed_reclaim:
                shortage = needed_reclaim - host_free_ram
                host_free_ram = 0
                host_swap_used += shortage
                if guest_swap_used > 0:
                    double_swapping_detected = True

    # Root Cause Diagnosis
    if len(oom_killed_pids) > 0:
        root_cause = "GUEST_OOM_KILL_DUE_TO_DISABLED_DEFLATE_ON_OOM"
    elif double_swapping_detected:
        root_cause = "HOST_GUEST_DOUBLE_SWAP_THRASHING"
    elif direct_reclaim_stalls >= 2 or (max_inflation_rate == 0 and direct_reclaim_stalls >= 1):
        root_cause = "BALLOON_RAPID_INFLATION_DIRECT_RECLAIM_STALL"
    elif shattered_thp_count >= 512:
        root_cause = "THP_SHATTERING_TLB_PERFORMANCE_DEGRADATION"
    else:
        root_cause = "STABLE_BALLOON_OPERATION"

    # Actionable Recommendations
    recommendations = []
    if not deflate_on_oom:
        recommendations.append("ENABLE_VIRTIO_BALLOON_DEFLATE_ON_OOM")
    if max_inflation_rate == 0:
        recommendations.append("RATE_LIMIT_INFLATION_STEPS")
    if granularity == "4KB" and thp_enabled:
        recommendations.append("MIGRATE_TO_VIRTIO_MEM_PRESERVE_THP")
    if guest_swap_total > 0:
        recommendations.append("DISABLE_GUEST_SWAP_UNDER_OVERCOMMIT")

    if not recommendations:
        recommendations.append("MONITOR_BALLOON_AND_COMPACT_MEMORY")

    living_procs = [
        {"pid": p["pid"], "name": p["name"], "rss_mb": p["rss_mb"]}
        for p in processes.values() if not p["killed"]
    ]

    return {
        "final_state": {
            "balloon_inflated_mb": balloon_inflated,
            "free_ram_mb": free_ram,
            "page_cache_mb": page_cache,
            "guest_swap_used_mb": guest_swap_used,
            "host_swap_used_mb": host_swap_used
        },
        "metrics": {
            "direct_reclaim_stalls": direct_reclaim_stalls,
            "oom_killed_pids": oom_killed_pids,
            "thp_shattered_count_2mb": shattered_thp_count,
            "double_swapping_detected": double_swapping_detected
        },
        "living_processes": living_procs,
        "root_cause": root_cause,
        "recommendations": recommendations
    }

def main():
    try:
        input_data = sys.stdin.read().strip()
        if not input_data:
            return
        data = json.loads(input_data)
        result = simulate_balloon(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
