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

PAGE_SIZE_KB = 4
HUGEPAGE_ORDER = 9
HUGEPAGE_PAGES = 1 << HUGEPAGE_ORDER  # 512

def calc_percentile(sorted_list, pct):
    if not sorted_list:
        return 0.0
    idx = max(0, min(len(sorted_list) - 1, math.ceil(pct / 100.0 * len(sorted_list)) - 1))
    return sorted_list[idx]

def simulate_linux_thp_mm(input_data: dict) -> dict:
    config = input_data["config"]
    initial_memory = input_data["initial_memory"]
    requests = input_data["requests"]

    total_pages = config.get("total_pages", 4096)
    min_free_pages = config.get("min_free_pages", 256)
    scale_factor = config.get("watermark_scale_factor", 10)
    w_min = min_free_pages
    w_low = w_min + int(w_min * scale_factor / 100)
    w_high = w_min + 2 * int(w_min * scale_factor / 100)

    thp_enabled = config.get("thp_enabled", "always")
    thp_defrag = config.get("thp_defrag", "always")
    latency_sla_us = config.get("latency_sla_us", 500.0)

    cost_base_alloc_us = config.get("cost_base_alloc_us", 0.5)
    cost_migration_us = config.get("cost_migration_us", 2.0)
    cost_clean_reclaim_us = config.get("cost_clean_reclaim_us", 1.0)
    cost_dirty_reclaim_us = config.get("cost_dirty_reclaim_us", 25.0)

    page_state = ["FREE"] * total_pages
    for seg in initial_memory.get("segments", []):
        st = seg["start_pfn"]
        cnt = seg["count"]
        typ = seg["type"]
        for p in range(st, min(st + cnt, total_pages)):
            page_state[p] = typ

    def get_free_indices():
        return [i for i, s in enumerate(page_state) if s == "FREE"]

    def find_aligned_free_order9():
        num_blocks = total_pages // HUGEPAGE_PAGES
        for b in range(num_blocks):
            base = b * HUGEPAGE_PAGES
            if all(page_state[base + i] == "FREE" for i in range(HUGEPAGE_PAGES)):
                return base
        return -1

    def find_best_compactable_block():
        num_blocks = total_pages // HUGEPAGE_PAGES
        best_block = -1
        min_migrations = HUGEPAGE_PAGES + 1

        for b in range(num_blocks):
            base = b * HUGEPAGE_PAGES
            block = page_state[base:base + HUGEPAGE_PAGES]
            if "UNMOVABLE" in block:
                continue
            movables = sum(1 for s in block if s.startswith("MOVABLE"))
            if movables == 0:
                return base, 0
            if movables < min_migrations:
                min_migrations = movables
                best_block = b

        if best_block != -1:
            return best_block * HUGEPAGE_PAGES, min_migrations
        return -1, -1

    def perform_direct_reclaim(pages_needed_free):
        nonlocal page_state
        reclaimed_clean = 0
        reclaimed_dirty = 0
        reclaim_cost = 0.0

        current_free = len(get_free_indices())
        target_free = w_high + pages_needed_free
        deficit = target_free - current_free
        if deficit <= 0:
            return 0, 0, 0.0

        for p in range(total_pages):
            if deficit <= 0:
                break
            if page_state[p] == "MOVABLE_CLEAN":
                page_state[p] = "FREE"
                reclaimed_clean += 1
                reclaim_cost += cost_clean_reclaim_us
                deficit -= 1

        for p in range(total_pages):
            if deficit <= 0:
                break
            if page_state[p] == "MOVABLE_DIRTY":
                page_state[p] = "FREE"
                reclaimed_dirty += 1
                reclaim_cost += cost_dirty_reclaim_us
                deficit -= 1

        return reclaimed_clean, reclaimed_dirty, reclaim_cost

    alloc_logs = []
    spike_count = 0
    direct_reclaim_event_count = 0
    compaction_event_count = 0
    thp_requests_count = 0
    thp_success_count = 0
    latencies = []

    for req in requests:
        req_id = req["id"]
        size_bytes = req["size_bytes"]
        is_madvise = req.get("madvise_hugepage", False)

        pages_needed = math.ceil(size_bytes / (PAGE_SIZE_KB * 1024))
        want_thp = (pages_needed >= HUGEPAGE_PAGES)

        latency = cost_base_alloc_us
        compacted_pages = 0
        reclaimed_pages = 0
        alloc_status = "OOM"

        if want_thp:
            thp_requests_count += 1
            allow_thp = False
            if thp_enabled == "always":
                allow_thp = True
            elif thp_enabled == "madvise" and is_madvise:
                allow_thp = True

            thp_done = False
            if allow_thp:
                free_block_base = find_aligned_free_order9()
                if free_block_base != -1:
                    for i in range(HUGEPAGE_PAGES):
                        page_state[free_block_base + i] = "UNMOVABLE"
                    thp_done = True
                    thp_success_count += 1
                    alloc_status = "THP_ALLOCATED"
                else:
                    allow_sync_compaction = False
                    if thp_defrag == "always":
                        allow_sync_compaction = True
                    elif thp_defrag == "madvise" and is_madvise:
                        allow_sync_compaction = True

                    if allow_sync_compaction:
                        target_base, movable_cnt = find_best_compactable_block()
                        if target_base != -1:
                            ext_free_slots = [p for p in range(total_pages) if page_state[p] == "FREE" and not (target_base <= p < target_base + HUGEPAGE_PAGES)]
                            
                            if len(ext_free_slots) < movable_cnt:
                                rc_clean, rc_dirty, rc_cost = perform_direct_reclaim(movable_cnt)
                                if rc_clean + rc_dirty > 0:
                                    direct_reclaim_event_count += 1
                                    reclaimed_pages += (rc_clean + rc_dirty)
                                    latency += rc_cost
                                ext_free_slots = [p for p in range(total_pages) if page_state[p] == "FREE" and not (target_base <= p < target_base + HUGEPAGE_PAGES)]

                            if len(ext_free_slots) >= movable_cnt:
                                comp_slot = 0
                                for i in range(HUGEPAGE_PAGES):
                                    cur_p = target_base + i
                                    if page_state[cur_p].startswith("MOVABLE"):
                                        dest_p = ext_free_slots[comp_slot]
                                        page_state[dest_p] = page_state[cur_p]
                                        page_state[cur_p] = "FREE"
                                        comp_slot += 1
                                        compacted_pages += 1
                                        latency += cost_migration_us
                                compaction_event_count += 1

                                for i in range(HUGEPAGE_PAGES):
                                    page_state[target_base + i] = "UNMOVABLE"
                                thp_done = True
                                thp_success_count += 1
                                alloc_status = "THP_ALLOCATED"

            if not thp_done:
                free_slots = get_free_indices()
                if len(free_slots) < pages_needed or len(free_slots) < w_min:
                    rc_clean, rc_dirty, rc_cost = perform_direct_reclaim(pages_needed)
                    if rc_clean + rc_dirty > 0:
                        direct_reclaim_event_count += 1
                        reclaimed_pages += (rc_clean + rc_dirty)
                        latency += rc_cost
                    free_slots = get_free_indices()

                if len(free_slots) >= pages_needed:
                    for i in range(pages_needed):
                        page_state[free_slots[i]] = "MOVABLE_CLEAN"
                    alloc_status = "BASE_PAGES_ALLOCATED"
                else:
                    alloc_status = "OOM"

        else:
            free_slots = get_free_indices()
            if len(free_slots) < pages_needed or len(free_slots) < w_min:
                rc_clean, rc_dirty, rc_cost = perform_direct_reclaim(pages_needed)
                if rc_clean + rc_dirty > 0:
                    direct_reclaim_event_count += 1
                    reclaimed_pages += (rc_clean + rc_dirty)
                    latency += rc_cost
                free_slots = get_free_indices()

            if len(free_slots) >= pages_needed:
                for i in range(pages_needed):
                    page_state[free_slots[i]] = "MOVABLE_CLEAN"
                alloc_status = "BASE_PAGES_ALLOCATED"
            else:
                alloc_status = "OOM"

        latency_rounded = round(latency, 2)
        is_spike = (latency_rounded > latency_sla_us)
        if is_spike:
            spike_count += 1
        latencies.append(latency_rounded)

        alloc_logs.append({
            "id": req_id,
            "status": alloc_status,
            "allocated_pages": pages_needed if alloc_status != "OOM" else 0,
            "latency_us": latency_rounded,
            "compacted_pages": compacted_pages,
            "reclaimed_pages": reclaimed_pages,
            "latency_spike": is_spike
        })

    latencies_sorted = sorted(latencies)
    p50 = calc_percentile(latencies_sorted, 50)
    p99 = calc_percentile(latencies_sorted, 99)
    max_lat = latencies_sorted[-1] if latencies_sorted else 0.0

    thp_rate = round((thp_success_count / thp_requests_count) * 100, 2) if thp_requests_count > 0 else 0.0

    if spike_count > 0:
        if compaction_event_count > 0 and direct_reclaim_event_count > 0:
            recommendation = "REMEDY_DISABLE_THP_ALWAYS_AND_INCREASE_MIN_FREE"
        elif compaction_event_count > 0:
            recommendation = "REMEDY_SET_THP_DEFRAG_DEFER_OR_MADVISE"
        elif direct_reclaim_event_count > 0:
            recommendation = "REMEDY_TUNE_WATERMARKS_AND_BACKGROUND_KSWAPD"
        else:
            recommendation = "REMEDY_INVESTIGATE_LATENCY_SPIKES"
    else:
        recommendation = "PERFORMANCE_STABLE_WITHIN_SLA"

    return {
        "watermarks": {
            "w_min": w_min,
            "w_low": w_low,
            "w_high": w_high
        },
        "summary": {
            "total_requests": len(requests),
            "thp_requests": thp_requests_count,
            "thp_success_count": thp_success_count,
            "thp_success_rate_pct": thp_rate,
            "compaction_events": compaction_event_count,
            "direct_reclaim_events": direct_reclaim_event_count,
            "latency_spike_count": spike_count,
            "p50_latency_us": round(p50, 2),
            "p99_latency_us": round(p99, 2),
            "max_latency_us": round(max_lat, 2),
            "tuning_recommendation": recommendation
        },
        "allocations": alloc_logs
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = simulate_linux_thp_mm(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
