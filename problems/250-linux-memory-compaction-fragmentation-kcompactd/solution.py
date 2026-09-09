import json
import sys

def simulate_compaction(data):
    cfg = data["kernel_config"]
    proactiveness = cfg.get("compaction_proactiveness", 20)
    thp_defrag_policy = cfg.get("thp_defrag_policy", "always")
    min_free_kbytes_mb = cfg.get("min_free_kbytes_mb", 128)
    unmovable_isolation_enabled = cfg.get("unmovable_isolation_enabled", True)

    init = data["initial_state"]
    total_ram_mb = init["total_ram_mb"]
    free_ram_mb = init["free_ram_mb"]
    extfrag_score = init["external_fragmentation_score"]
    unmovable_contaminated_blocks = init.get("unmovable_contaminated_pageblocks", 0)
    free_order9_blocks = init.get("free_order9_blocks_2mb", 10)

    direct_compaction_stalls = 0
    thp_allocation_failures = 0
    kcompactd_wakeups = 0
    kcompactd_cpu_thrashing = False
    unmovable_pin_failures = 0

    kcompactd_thresh = 100 - proactiveness

    def run_kcompactd():
        nonlocal extfrag_score, free_order9_blocks, kcompactd_wakeups, kcompactd_cpu_thrashing
        if proactiveness == 0:
            return

        kcompactd_wakeups += 1
        if proactiveness > 80:
            kcompactd_cpu_thrashing = True

        if extfrag_score > kcompactd_thresh:
            reduction = min(extfrag_score, proactiveness)
            extfrag_score = max(5, extfrag_score - reduction)
            new_blocks = int(reduction * (free_ram_mb // 2) / 100)
            free_order9_blocks += max(1, new_blocks)

    def allocate_order9(count_blocks):
        nonlocal free_order9_blocks, direct_compaction_stalls, thp_allocation_failures
        nonlocal unmovable_pin_failures, extfrag_score

        for _ in range(count_blocks):
            if free_order9_blocks > 0:
                free_order9_blocks -= 1
                continue

            if thp_defrag_policy == "never":
                thp_allocation_failures += 1
                continue

            if unmovable_contaminated_blocks > 100:
                unmovable_pin_failures += 1
                thp_allocation_failures += 1
                continue

            if thp_defrag_policy in ("always", "defer"):
                if thp_defrag_policy == "defer":
                    run_kcompactd()
                    thp_allocation_failures += 1
                else:
                    direct_compaction_stalls += 1
                    if extfrag_score > 50:
                        extfrag_score = max(10, extfrag_score - 20)
                    else:
                        extfrag_score = max(5, extfrag_score - 10)

    events = sorted(data.get("events", []), key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]

        if ev_type == "PROACTIVE_COMPACT_TICK":
            run_kcompactd()

        elif ev_type == "ALLOC_HUGEPAGE_ORDER9":
            count = ev["count_2mb"]
            allocate_order9(count)

        elif ev_type == "KERNEL_SLAB_BURST":
            alloc_mb = ev["alloc_mb"]
            if not unmovable_isolation_enabled or min_free_kbytes_mb < 256:
                contaminated = alloc_mb // 2
                unmovable_contaminated_blocks += contaminated
                extfrag_score = min(100, extfrag_score + 30)

        elif ev_type == "DROP_CACHES":
            unmovable_contaminated_blocks = max(0, unmovable_contaminated_blocks - 50)
            extfrag_score = max(10, extfrag_score - 20)

    # Diagnosis Hierarchy
    if unmovable_pin_failures > 0:
        root_cause = "COMPACTION_FAILED_UNMOVABLE_PAGEBLOCK_CONTAMINATION"
    elif kcompactd_cpu_thrashing:
        root_cause = "KCOMPACTD_PROACTIVE_OVERTUNED_CPU_THRASHING"
    elif direct_compaction_stalls >= 2:
        root_cause = "DIRECT_COMPACTION_SYNCHRONOUS_LATENCY_STALL"
    else:
        root_cause = "STABLE_EFFICIENT_COMPACTION_AND_ALLOCATION"

    recommendations = []
    if proactiveness > 80 or proactiveness == 0:
        recommendations.append("TUNE_VM_COMPACTION_PROACTIVENESS_TO_RECOMMENDED_RANGE")
    if thp_defrag_policy == "always":
        recommendations.append("CHANGE_THP_DEFRAG_TO_DEFER_OR_MADVISE")
    if not unmovable_isolation_enabled or min_free_kbytes_mb < 256:
        recommendations.append("INCREASE_MIN_FREE_KBYTES_AND_ISOLATE_UNMOVABLE")

    if not recommendations:
        recommendations.append("MONITOR_EXTFRAG_INDEX_AND_COMPACTION_STATS")

    return {
        "final_state": {
            "external_fragmentation_score": extfrag_score,
            "free_order9_blocks_2mb": free_order9_blocks,
            "unmovable_contaminated_pageblocks": unmovable_contaminated_blocks
        },
        "metrics": {
            "direct_compaction_stalls": direct_compaction_stalls,
            "thp_allocation_failures": thp_allocation_failures,
            "kcompactd_wakeups": kcompactd_wakeups,
            "kcompactd_cpu_thrashing": kcompactd_cpu_thrashing,
            "unmovable_pin_failures": unmovable_pin_failures
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
        result = simulate_compaction(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
