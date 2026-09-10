import sys
import json

class LeveledCompactionEngine:
    def __init__(self, max_levels=4, l0_threshold=4, l1_target_bytes=500, level_multiplier=5, target_file_size=250):
        self.max_levels = max_levels
        self.l0_threshold = l0_threshold
        self.l1_target_bytes = l1_target_bytes
        self.level_multiplier = level_multiplier
        self.target_file_size = target_file_size
        
        self.levels = [[] for _ in range(max_levels)]
        self.file_counter = 1
        self.user_bytes_written = 0
        self.stats = {
            "compactions_executed": 0,
            "bytes_read": 0,
            "bytes_written": 0,
            "tombstones_purged": 0,
            "tombstones_preserved": 0
        }

    def level_target_bytes(self, level):
        if level == 0:
            return self.l0_threshold
        return self.l1_target_bytes * (self.level_multiplier ** (level - 1))

    def add_memtable_flush(self, entries):
        entries.sort(key=lambda x: (x["key"], x["seq"]))
        size = sum(len(e["key"]) + (len(e["val"]) if e["val"] is not None else 0) + 8 for e in entries)
        self.user_bytes_written += size
        self.stats["bytes_written"] += size
        
        min_k = min(e["key"] for e in entries)
        max_k = max(e["key"] for e in entries)
        
        sst = {
            "file_id": f"SST-{self.file_counter:04d}",
            "level": 0,
            "min_key": min_k,
            "max_key": max_k,
            "size_bytes": size,
            "entries": entries
        }
        self.file_counter += 1
        self.levels[0].append(sst)
        return sst

    def compute_scores(self):
        scores = []
        l0_score = round(len(self.levels[0]) / self.l0_threshold, 2)
        scores.append({"level": 0, "score": l0_score, "files": len(self.levels[0]), "bytes": sum(f["size_bytes"] for f in self.levels[0])})
        
        for lvl in range(1, self.max_levels):
            tot_b = sum(f["size_bytes"] for f in self.levels[lvl])
            target = self.level_target_bytes(lvl)
            score = round(tot_b / target, 2)
            scores.append({"level": lvl, "score": score, "files": len(self.levels[lvl]), "bytes": tot_b})
            
        return scores

    def _key_exists_in_deeper_levels(self, key, start_level):
        for lvl in range(start_level, self.max_levels):
            for sst in self.levels[lvl]:
                if sst["min_key"] <= key <= sst["max_key"]:
                    for e in sst["entries"]:
                        if e["key"] == key:
                            return True
        return False

    def pick_compaction(self):
        scores = self.compute_scores()
        candidates = [s for s in scores if s["score"] >= 1.0 and s["level"] < self.max_levels - 1]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x["score"], -x["level"]), reverse=True)
        chosen_lvl = candidates[0]["level"]
        
        if chosen_lvl == 0:
            input_files = list(self.levels[0])
        else:
            input_files = [self.levels[chosen_lvl][0]]
            
        min_k = min(f["min_key"] for f in input_files)
        max_k = max(f["max_key"] for f in input_files)
        
        next_lvl = chosen_lvl + 1
        overlapping = []
        for f in self.levels[next_lvl]:
            if not (f["max_key"] < min_k or f["min_key"] > max_k):
                overlapping.append(f)
                
        return {
            "source_level": chosen_lvl,
            "target_level": next_lvl,
            "source_files": input_files,
            "overlapping_files": overlapping
        }

    def execute_compaction(self):
        plan = self.pick_compaction()
        if not plan:
            return None
            
        src_lvl = plan["source_level"]
        tgt_lvl = plan["target_level"]
        src_files = plan["source_files"]
        ovl_files = plan["overlapping_files"]
        
        all_inputs = src_files + ovl_files
        read_bytes = sum(f["size_bytes"] for f in all_inputs)
        self.stats["bytes_read"] += read_bytes
        self.stats["compactions_executed"] += 1
        
        merged_map = {}
        for f in all_inputs:
            for e in f["entries"]:
                k = e["key"]
                if k not in merged_map or e["seq"] > merged_map[k]["seq"]:
                    merged_map[k] = e
                    
        final_entries = []
        for k in sorted(merged_map.keys()):
            e = merged_map[k]
            if e.get("is_tombstone", False):
                if not self._key_exists_in_deeper_levels(k, tgt_lvl + 1):
                    self.stats["tombstones_purged"] += 1
                else:
                    self.stats["tombstones_preserved"] += 1
                    final_entries.append(e)
            else:
                final_entries.append(e)
                
        new_ssts = []
        cur_chunk = []
        cur_size = 0
        
        for e in final_entries:
            e_size = len(e["key"]) + (len(e["val"]) if e["val"] is not None else 0) + 8
            if cur_size + e_size > self.target_file_size and cur_chunk:
                sst = {
                    "file_id": f"SST-{self.file_counter:04d}",
                    "level": tgt_lvl,
                    "min_key": cur_chunk[0]["key"],
                    "max_key": cur_chunk[-1]["key"],
                    "size_bytes": cur_size,
                    "entries": cur_chunk
                }
                self.file_counter += 1
                new_ssts.append(sst)
                cur_chunk = []
                cur_size = 0
            cur_chunk.append(e)
            cur_size += e_size
            
        if cur_chunk:
            sst = {
                "file_id": f"SST-{self.file_counter:04d}",
                "level": tgt_lvl,
                "min_key": cur_chunk[0]["key"],
                "max_key": cur_chunk[-1]["key"],
                "size_bytes": cur_size,
                "entries": cur_chunk
            }
            self.file_counter += 1
            new_ssts.append(sst)
            
        written_bytes = sum(f["size_bytes"] for f in new_ssts)
        self.stats["bytes_written"] += written_bytes
        
        src_ids = {f["file_id"] for f in src_files}
        ovl_ids = {f["file_id"] for f in ovl_files}
        
        self.levels[src_lvl] = [f for f in self.levels[src_lvl] if f["file_id"] not in src_ids]
        self.levels[tgt_lvl] = [f for f in self.levels[tgt_lvl] if f["file_id"] not in ovl_ids]
        
        self.levels[tgt_lvl].extend(new_ssts)
        self.levels[tgt_lvl].sort(key=lambda f: f["min_key"])
        
        return {
            "source_level": src_lvl,
            "target_level": tgt_lvl,
            "input_file_ids": [f["file_id"] for f in all_inputs],
            "output_file_ids": [f["file_id"] for f in new_ssts],
            "read_bytes": read_bytes,
            "written_bytes": written_bytes
        }

    def point_lookup(self, key):
        seeks = 0
        for f in reversed(self.levels[0]):
            seeks += 1
            if f["min_key"] <= key <= f["max_key"]:
                for e in reversed(f["entries"]):
                    if e["key"] == key:
                        return {
                            "key": key,
                            "found": not e.get("is_tombstone", False),
                            "val": e["val"],
                            "seq": e["seq"],
                            "level_found": 0,
                            "file_id": f["file_id"],
                            "is_tombstone": e.get("is_tombstone", False),
                            "sst_seeks": seeks
                        }
                        
        for lvl in range(1, self.max_levels):
            for f in self.levels[lvl]:
                if f["min_key"] <= key <= f["max_key"]:
                    seeks += 1
                    for e in f["entries"]:
                        if e["key"] == key:
                            return {
                                "key": key,
                                "found": not e.get("is_tombstone", False),
                                "val": e["val"],
                                "seq": e["seq"],
                                "level_found": lvl,
                                "file_id": f["file_id"],
                                "is_tombstone": e.get("is_tombstone", False),
                                "sst_seeks": seeks
                            }
                    break
                    
        return {
            "key": key,
            "found": False,
            "val": None,
            "seq": None,
            "level_found": None,
            "file_id": None,
            "is_tombstone": False,
            "sst_seeks": seeks
        }

    def get_snapshot(self):
        level_status = []
        for lvl in range(self.max_levels):
            files = self.levels[lvl]
            tot_b = sum(f["size_bytes"] for f in files)
            target = self.level_target_bytes(lvl)
            score = round(tot_b / target, 2) if lvl > 0 else round(len(files) / self.l0_threshold, 2)
            level_status.append({
                "level": lvl,
                "file_count": len(files),
                "total_bytes": tot_b,
                "target_capacity": target,
                "score": score,
                "file_ranges": [f"{f['file_id']}[{f['min_key']}..{f['max_key']}]" for f in files]
            })
            
        wa = round(self.stats["bytes_written"] / self.user_bytes_written, 2) if self.user_bytes_written > 0 else 1.0
        
        return {
            "levels": level_status,
            "metrics": {
                "user_bytes_written": self.user_bytes_written,
                "total_bytes_written": self.stats["bytes_written"],
                "total_bytes_read": self.stats["bytes_read"],
                "write_amplification": wa,
                "compactions_executed": self.stats["compactions_executed"],
                "tombstones_purged": self.stats["tombstones_purged"],
                "tombstones_preserved": self.stats["tombstones_preserved"]
            }
        }

def run_simulation(req):
    cfg = req.get("config", {})
    engine = LeveledCompactionEngine(
        max_levels=cfg.get("max_levels", 4),
        l0_threshold=cfg.get("l0_threshold", 4),
        l1_target_bytes=cfg.get("l1_target_bytes", 500),
        level_multiplier=cfg.get("level_multiplier", 5),
        target_file_size=cfg.get("target_file_size", 250)
    )
    
    logs = []
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "FLUSH_MEMTABLE":
            entries = op_item["entries"]
            sst = engine.add_memtable_flush(entries)
            logs.append({
                "step": step,
                "op": op,
                "file_id": sst["file_id"],
                "level": sst["level"],
                "min_key": sst["min_key"],
                "max_key": sst["max_key"],
                "size_bytes": sst["size_bytes"],
                "entry_count": len(entries)
            })
            
        elif op == "COMPACT":
            res = engine.execute_compaction()
            logs.append({
                "step": step,
                "op": op,
                "compaction_performed": res is not None,
                "details": res
            })
            
        elif op == "GET":
            k = op_item["key"]
            res = engine.point_lookup(k)
            logs.append({
                "step": step,
                "op": op,
                **res
            })
            
        elif op == "GET_SNAPSHOT":
            snap = engine.get_snapshot()
            logs.append({
                "step": step,
                "op": op,
                "snapshot": snap
            })
            
    final_snap = engine.get_snapshot()
    return {
        "operations_log": logs,
        "final_state": final_snap
    }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    raw_in = sys.stdin.read().strip()
    if not raw_in:
        return
        
    req = json.loads(raw_in)
    res = run_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
