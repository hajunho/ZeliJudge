import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    max_nr_gens = data.get("max_nr_gens", 4)
    initial_pages = data.get("initial_pages", [])
    operations = data.get("operations", [])
    
    max_seq = 0
    min_seq = 0
    pages = {}
    evicted_history = set()
    
    stats = {
        "allocated_count": 0,
        "promoted_count": 0,
        "evicted_clean_file": 0,
        "evicted_dirty_file": 0,
        "evicted_anon_swap": 0,
        "refault_count": 0
    }
    
    for p in initial_pages:
        pid = p["page_id"]
        pages[pid] = {
            "page_id": pid,
            "type": p.get("type", "file"),
            "dirty": p.get("dirty", False),
            "gen": p.get("gen", 0),
            "tier": max(0, min(3, p.get("tier", 0))),
            "accessed": p.get("accessed", False)
        }
        
    if pages:
        min_seq = min(p["gen"] for p in pages.values())
        max_seq = max(p["gen"] for p in pages.values())
        
    op_log = []
    
    for op in operations:
        op_name = op.get("op")
        
        if op_name == "ALLOC_PAGE":
            pid = op["page_id"]
            ptype = op.get("type", "file")
            dirty = op.get("dirty", False)
            init_tier = max(0, min(3, op.get("tier", 0)))
            
            is_refault = (pid in evicted_history)
            if is_refault:
                stats["refault_count"] += 1
                evicted_history.remove(pid)
                
            pages[pid] = {
                "page_id": pid,
                "type": ptype,
                "dirty": dirty,
                "gen": max_seq,
                "tier": init_tier,
                "accessed": False
            }
            stats["allocated_count"] += 1
            op_log.append({
                "op": "ALLOC_PAGE",
                "page_id": pid,
                "gen": max_seq,
                "tier": init_tier,
                "is_refault": is_refault
            })
            
        elif op_name == "ACCESS_PAGE":
            pid = op["page_id"]
            count = op.get("count", 1)
            if pid in pages:
                p = pages[pid]
                p["accessed"] = True
                p["tier"] = min(3, p["tier"] + count)
                op_log.append({
                    "op": "ACCESS_PAGE",
                    "page_id": pid,
                    "new_tier": p["tier"],
                    "accessed": True
                })
            else:
                op_log.append({
                    "op": "ACCESS_PAGE",
                    "page_id": pid,
                    "status": "PAGE_NOT_FOUND"
                })
                
        elif op_name == "PAGE_TABLE_SCAN":
            scanned_pages = 0
            tiers_advanced = 0
            for pid in sorted(pages.keys()):
                p = pages[pid]
                if p["accessed"]:
                    scanned_pages += 1
                    p["tier"] = min(3, p["tier"] + 1)
                    p["accessed"] = False
                    tiers_advanced += 1
            op_log.append({
                "op": "PAGE_TABLE_SCAN",
                "scanned_accessed": scanned_pages,
                "tiers_advanced": tiers_advanced
            })
            
        elif op_name == "AGING":
            step = op.get("step", 1)
            for _ in range(step):
                max_seq += 1
                if (max_seq - min_seq + 1) > max_nr_gens:
                    min_seq = max_seq - max_nr_gens + 1
            op_log.append({
                "op": "AGING",
                "max_seq": max_seq,
                "min_seq": min_seq
            })
            
        elif op_name == "CLEAN_DIRTY_FILES":
            cleaned_count = 0
            for p in pages.values():
                if p["type"] == "file" and p["dirty"]:
                    p["dirty"] = False
                    cleaned_count += 1
            op_log.append({
                "op": "CLEAN_DIRTY_FILES",
                "cleaned_count": cleaned_count
            })
            
        elif op_name == "RECLAIM":
            nr_to_reclaim = op.get("nr_to_reclaim", 1)
            target_type = op.get("type", "all")
            
            reclaimed_pids = []
            promoted_pids = []
            
            while len(reclaimed_pids) < nr_to_reclaim and min_seq <= max_seq:
                candidates = [p for p in pages.values() if p["gen"] == min_seq]
                if target_type != "all":
                    candidates = [p for p in candidates if p["type"] == target_type]
                    
                if not candidates:
                    if min_seq < max_seq:
                        min_seq += 1
                        continue
                    else:
                        break
                        
                candidates.sort(key=lambda x: (x["tier"], x["accessed"], x["page_id"]))
                
                progress = False
                for p in candidates:
                    if len(reclaimed_pids) >= nr_to_reclaim:
                        break
                        
                    pid = p["page_id"]
                    if p["tier"] > 0 or p["accessed"]:
                        if min_seq < max_seq:
                            p["gen"] = max_seq
                            p["tier"] = max(0, p["tier"] - 1)
                            p["accessed"] = False
                            promoted_pids.append(pid)
                            stats["promoted_count"] += 1
                            progress = True
                        else:
                            if p["accessed"]:
                                p["accessed"] = False
                                progress = True
                            elif p["tier"] > 0:
                                p["tier"] -= 1
                                progress = True
                            else:
                                reclaimed_pids.append(pid)
                                evicted_history.add(pid)
                                if p["type"] == "file":
                                    if p["dirty"]:
                                        stats["evicted_dirty_file"] += 1
                                    else:
                                        stats["evicted_clean_file"] += 1
                                else:
                                    stats["evicted_anon_swap"] += 1
                                del pages[pid]
                                progress = True
                    else:
                        reclaimed_pids.append(pid)
                        evicted_history.add(pid)
                        if p["type"] == "file":
                            if p["dirty"]:
                                stats["evicted_dirty_file"] += 1
                            else:
                                stats["evicted_clean_file"] += 1
                        else:
                            stats["evicted_anon_swap"] += 1
                        del pages[pid]
                        progress = True
                        
                if not progress:
                    if min_seq < max_seq:
                        min_seq += 1
                    else:
                        break
                        
            while min_seq < max_seq and not any(p["gen"] == min_seq for p in pages.values()):
                min_seq += 1
                
            op_log.append({
                "op": "RECLAIM",
                "reclaimed_count": len(reclaimed_pids),
                "reclaimed_pages": reclaimed_pids,
                "promoted_count": len(promoted_pids),
                "promoted_pages": promoted_pids,
                "current_min_seq": min_seq
            })

    gen_dist = {}
    for g in range(min_seq, max_seq + 1):
        gen_dist[g] = 0
    for p in pages.values():
        g = p["gen"]
        gen_dist[g] = gen_dist.get(g, 0) + 1
        
    tier_dist = {0: 0, 1: 0, 2: 0, 3: 0}
    for p in pages.values():
        tier_dist[p["tier"]] = tier_dist.get(p["tier"], 0) + 1
        
    wss = sum(1 for p in pages.values() if p["gen"] > min_seq or p["tier"] > 0)
    
    total_evictions = (stats["evicted_clean_file"] + stats["evicted_dirty_file"] + stats["evicted_anon_swap"])
    refault_ratio = round(stats["refault_count"] / max(1, total_evictions), 4)
    thrashing_detected = (stats["refault_count"] >= 2 and refault_ratio >= 0.25)
    
    result = {
        "max_seq": max_seq,
        "min_seq": min_seq,
        "active_page_count": len(pages),
        "working_set_size": wss,
        "generation_distribution": {str(k): v for k, v in sorted(gen_dist.items())},
        "tier_distribution": {f"tier_{k}": v for k, v in sorted(tier_dist.items())},
        "stats": stats,
        "thrashing_analysis": {
            "total_evictions": total_evictions,
            "refault_count": stats["refault_count"],
            "refault_ratio": refault_ratio,
            "thrashing_detected": thrashing_detected
        },
        "op_log": op_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
