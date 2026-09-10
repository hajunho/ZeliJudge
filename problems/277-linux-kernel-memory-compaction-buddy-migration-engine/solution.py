import sys
import json

# Ensure UTF-8 IO
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

PAGE_FREE = 0
PAGE_ALLOCATED_MOVABLE = 1
PAGE_ALLOCATED_UNMOVABLE = 2

def has_buddy_aligned_free(all_pfns, pfn_to_page, target_order):
    block_size = 1 << target_order
    min_pfn = all_pfns[0]
    max_pfn = all_pfns[-1]
    
    start_pfn = min_pfn - (min_pfn % block_size)
    if start_pfn < min_pfn:
        start_pfn += block_size
        
    for cand in range(start_pfn, max_pfn - block_size + 2, block_size):
        all_free = True
        for i in range(block_size):
            p = cand + i
            if p not in pfn_to_page or pfn_to_page[p]["state"] != PAGE_FREE:
                all_free = False
                break
        if all_free:
            return True, cand
    return False, None

def find_highest_order(all_pfns, pfn_to_page, max_order_limit=8):
    for order in range(max_order_limit, -1, -1):
        found, _ = has_buddy_aligned_free(all_pfns, pfn_to_page, order)
        if found:
            return order
    return 0

def calculate_frag_index(total_pages, free_pages, target_pages, max_order_available, target_order):
    if free_pages < target_pages:
        return 0
    if max_order_available >= target_order:
        return 0
    covered = 1 << max_order_available
    score = int(round(1000.0 * (1.0 - (covered / free_pages))))
    return max(0, min(1000, score))

def build_result(status, initial_stats, target_order, target_pages, migrated_count,
                 mig_pfn, free_pfn, converged, allocated_buddy_pfn, all_pfns, pfn_to_page, pageblocks_info, **kwargs):
    if allocated_buddy_pfn is None and "allocated_pfn" in kwargs:
        allocated_buddy_pfn = kwargs["allocated_pfn"]
    curr_free = sum(1 for pfn in all_pfns if pfn_to_page[pfn]["state"] == PAGE_FREE)
    final_max_order = find_highest_order(all_pfns, pfn_to_page)
    target_avail = (allocated_buddy_pfn is not None)

    
    final_pbs = []
    for pb in pageblocks_info:
        p_start = pb["pfn_start"]
        length = pb["length"]
        states = [pfn_to_page[p_start + i]["state"] for i in range(length)]
        fc = sum(1 for s in states if s == PAGE_FREE)
        final_pbs.append({
            "pfn_start": p_start,
            "migratetype": pb["migratetype"],
            "free_count": fc,
            "pages": states
        })
        
    return {
        "status": status,
        "initial_stats": initial_stats,
        "compaction_result": {
            "target_order": target_order,
            "target_pages": target_pages,
            "migrated_pages_count": migrated_count,
            "migrate_scanner_final_pfn": mig_pfn,
            "free_scanner_final_pfn": free_pfn,
            "scanners_converged": converged,
            "allocated_buddy_pfn": allocated_buddy_pfn
        },
        "final_stats": {
            "free_pages": curr_free,
            "max_available_order": final_max_order,
            "target_order_available": target_avail
        },
        "final_pageblocks": final_pbs
    }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    req = json.loads(raw)
    
    zone_start = req["zone_start_pfn"]
    pb_size = req.get("pageblock_size", 16)
    target_order = req["target_order"]
    target_pages = 1 << target_order
    min_wm = req.get("min_watermark_pages", 0)
    
    pfn_to_page = {}
    all_pfns = []
    pageblocks_info = []
    
    for pb in req["pageblocks"]:
        p_start = pb["pfn_start"]
        mtype = pb["migratetype"]
        page_states = list(pb["pages"])
        pageblocks_info.append({
            "pfn_start": p_start,
            "migratetype": mtype,
            "length": len(page_states)
        })
        for idx, p_state in enumerate(page_states):
            pfn = p_start + idx
            pfn_to_page[pfn] = {
                "state": p_state,
                "pfn": pfn,
                "pb_start": p_start,
                "migratetype": mtype
            }
            all_pfns.append(pfn)
            
    all_pfns.sort()
    total_pages = len(all_pfns)
    initial_free = sum(1 for pfn in all_pfns if pfn_to_page[pfn]["state"] == PAGE_FREE)
    init_max_order = find_highest_order(all_pfns, pfn_to_page)
    frag_idx = calculate_frag_index(total_pages, initial_free, target_pages, init_max_order, target_order)
    
    initial_stats = {
        "total_pages": total_pages,
        "free_pages": initial_free,
        "max_available_order": init_max_order,
        "fragmentation_index": frag_idx
    }
    
    # 1. Watermark check
    if initial_free < min_wm + target_pages:
        res = build_result(
            status="COMPACT_SKIPPED_WATERMARK",
            initial_stats=initial_stats,
            target_order=target_order,
            target_pages=target_pages,
            migrated_count=0,
            mig_pfn=all_pfns[0],
            free_pfn=all_pfns[-1],
            converged=False,
            allocated_buddy_pfn=None,
            all_pfns=all_pfns,
            pfn_to_page=pfn_to_page,
            pageblocks_info=pageblocks_info
        )
        print(json.dumps(res, ensure_ascii=False))
        return
        
    # 2. Already satisfied check
    has_target, cand_pfn = has_buddy_aligned_free(all_pfns, pfn_to_page, target_order)
    if has_target:
        res = build_result(
            status="COMPACT_ALREADY_SATISFIED",
            initial_stats=initial_stats,
            target_order=target_order,
            target_pages=target_pages,
            migrated_count=0,
            mig_pfn=all_pfns[0],
            free_pfn=all_pfns[-1],
            converged=False,
            allocated_buddy_pfn=cand_pfn,
            all_pfns=all_pfns,
            pfn_to_page=pfn_to_page,
            pageblocks_info=pageblocks_info
        )
        print(json.dumps(res, ensure_ascii=False))
        return

    # 3. Two-Scanner Compaction loop
    migrate_pfn = all_pfns[0]
    free_pfn = all_pfns[-1]
    migrated_count = 0
    max_steps = req.get("max_steps", 20000)
    steps = 0
    
    while migrate_pfn < free_pfn and steps < max_steps:
        steps += 1
        
        while migrate_pfn < free_pfn:
            pg = pfn_to_page[migrate_pfn]
            if pg["migratetype"] == "UNMOVABLE":
                offset_in_pb = (migrate_pfn - pg["pb_start"])
                rem = pb_size - offset_in_pb
                migrate_pfn += max(1, rem)
                continue
            if pg["state"] == PAGE_ALLOCATED_MOVABLE:
                break
            migrate_pfn += 1
            
        while free_pfn > migrate_pfn:
            pg = pfn_to_page[free_pfn]
            if pg["state"] == PAGE_FREE:
                break
            free_pfn -= 1
            
        if migrate_pfn >= free_pfn:
            break
            
        pfn_to_page[free_pfn]["state"] = PAGE_ALLOCATED_MOVABLE
        pfn_to_page[migrate_pfn]["state"] = PAGE_FREE
        migrated_count += 1
        
        has_target, cand_pfn = has_buddy_aligned_free(all_pfns, pfn_to_page, target_order)
        if has_target:
            res = build_result(
                status="COMPACT_SUCCESS",
                initial_stats=initial_stats,
                target_order=target_order,
                target_pages=target_pages,
                migrated_count=migrated_count,
                mig_pfn=migrate_pfn,
                free_pfn=free_pfn,
                converged=False,
                allocated_buddy_pfn=cand_pfn,
                all_pfns=all_pfns,
                pfn_to_page=pfn_to_page,
                pageblocks_info=pageblocks_info
            )
            print(json.dumps(res, ensure_ascii=False))
            return
            
        migrate_pfn += 1
        free_pfn -= 1
        
    has_target, cand_pfn = has_buddy_aligned_free(all_pfns, pfn_to_page, target_order)
    status = "COMPACT_SUCCESS" if has_target else "COMPACT_FAILED_EXHAUSTED"
    
    res = build_result(
        status=status,
        initial_stats=initial_stats,
        target_order=target_order,
        target_pages=target_pages,
        migrated_count=migrated_count,
        mig_pfn=migrate_pfn,
        free_pfn=free_pfn,
        converged=(migrate_pfn >= free_pfn),
        allocated_buddy_pfn=cand_pfn,
        all_pfns=all_pfns,
        pfn_to_page=pfn_to_page,
        pageblocks_info=pageblocks_info
    )
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
