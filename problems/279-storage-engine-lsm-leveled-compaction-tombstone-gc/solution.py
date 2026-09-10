import sys
import json

# Ensure UTF-8 IO
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def summarize_levels(levels):
    summary = {}
    for lname, files in levels.items():
        total_k = sum(len(f["keys"]) for f in files)
        file_summaries = []
        for f in files:
            keys = [k["key"] for k in f["keys"]]
            file_summaries.append({
                "file_id": f["file_id"],
                "entry_count": len(keys),
                "key_range": f"{keys[0]}..{keys[-1]}" if keys else ""
            })
        summary[lname] = {
            "file_count": len(files),
            "entry_count": total_k,
            "files": file_summaries
        }
    return summary

def run_lsm_compaction(config):
    l0_trigger = config.get("l0_compaction_trigger", 4)
    target_file_size = config.get("target_file_size", 4)
    level_targets = config.get("level_targets", {"L1": 8, "L2": 32, "L3": 128})
    max_levels = config.get("max_levels", 4)
    
    levels = {f"L{i}": [] for i in range(max_levels)}
    for l_name, files in config.get("levels", {}).items():
        levels[l_name] = [dict(f) for f in files]
        
    scores = {}
    l0_count = len(levels["L0"])
    scores["L0"] = round(l0_count / l0_trigger, 3)
    
    for i in range(1, max_levels):
        lname = f"L{i}"
        cur_entries = sum(len(f["keys"]) for f in levels[lname])
        tgt = level_targets.get(lname, 1000)
        scores[lname] = round(cur_entries / tgt, 3)
        
    cand_levels = [(lname, sc) for lname, sc in scores.items() if sc >= 1.0]
    if not cand_levels:
        return {
            "compaction_needed": False,
            "compaction_scores": scores,
            "action_taken": "NO_COMPACTION",
            "levels_summary": summarize_levels(levels)
        }
        
    cand_levels.sort(key=lambda x: -x[1])
    comp_level = cand_levels[0][0]
    next_level = f"L{int(comp_level[1]) + 1}"
    
    if int(comp_level[1]) + 1 >= max_levels:
        return {
            "compaction_needed": True,
            "compaction_scores": scores,
            "action_taken": "BOTTOM_LEVEL_CANNOT_COMPACT",
            "levels_summary": summarize_levels(levels)
        }

    if comp_level == "L0":
        input_files_src = list(levels["L0"])
    else:
        input_files_src = [levels[comp_level][0]]
        
    all_src_keys = []
    for f in input_files_src:
        for k in f["keys"]:
            all_src_keys.append(k["key"])
            
    min_k = min(all_src_keys)
    max_k = max(all_src_keys)
    
    input_files_dst = []
    kept_files_dst = []
    for f in levels[next_level]:
        f_min = min(k["key"] for k in f["keys"])
        f_max = max(k["key"] for k in f["keys"])
        if not (f_max < min_k or f_min > max_k):
            input_files_dst.append(f)
        else:
            kept_files_dst.append(f)
            
    all_entries = []
    for f in input_files_src + input_files_dst:
        for k in f["keys"]:
            all_entries.append(k)
            
    all_entries.sort(key=lambda x: (x["key"], -x["seq"]))
    
    deduped = []
    curr_key = None
    
    is_bottommost = (int(next_level[1]) == max_levels - 1)
    lower_level_keys = set()
    for l_idx in range(int(next_level[1]) + 1, max_levels):
        for f in levels[f"L{l_idx}"]:
            for k in f["keys"]:
                lower_level_keys.add(k["key"])

    tombstones_dropped = 0
    tombstones_retained = 0
    
    for entry in all_entries:
        if entry["key"] == curr_key:
            continue
        curr_key = entry["key"]
        
        is_tombstone = (entry.get("val") is None or entry.get("val") == "TOMBSTONE")
        if is_tombstone:
            if is_bottommost or (curr_key not in lower_level_keys):
                tombstones_dropped += 1
                continue
            else:
                tombstones_retained += 1
                deduped.append(entry)
        else:
            deduped.append(entry)
            
    new_files = []
    file_idx = 1
    for i in range(0, len(deduped), target_file_size):
        chunk = deduped[i : i + target_file_size]
        new_fid = f"{next_level}_merged_{file_idx}"
        file_idx += 1
        new_files.append({
            "file_id": new_fid,
            "min_key": chunk[0]["key"],
            "max_key": chunk[-1]["key"],
            "keys": chunk
        })
        
    if comp_level == "L0":
        levels["L0"] = []
    else:
        src_fids = set(f["file_id"] for f in input_files_src)
        levels[comp_level] = [f for f in levels[comp_level] if f["file_id"] not in src_fids]
        
    all_next = kept_files_dst + new_files
    all_next.sort(key=lambda f: min(k["key"] for k in f["keys"]))
    levels[next_level] = all_next
    
    return {
        "compaction_needed": True,
        "compaction_scores": scores,
        "action_taken": f"COMPACT_{comp_level}_TO_{next_level}",
        "compaction_details": {
            "source_level": comp_level,
            "target_level": next_level,
            "source_files_count": len(input_files_src),
            "target_overlapping_files_count": len(input_files_dst),
            "output_new_files_count": len(new_files),
            "tombstones_dropped": tombstones_dropped,
            "tombstones_retained": tombstones_retained,
            "total_entries_compacted": len(all_entries),
            "total_entries_output": len(deduped)
        },
        "levels_summary": summarize_levels(levels)
    }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    config = json.loads(raw)
    res = run_lsm_compaction(config)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
