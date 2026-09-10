import sys
import json

class VfsDentryEngine:
    def __init__(self, max_negative_dentries=16, bloom_guard=False):
        self.max_negative = max_negative_dentries
        self.bloom_guard = bloom_guard
        
        self.inodes = {
            1: {"type": "DIR", "name": "/"}
        }
        self.inode_counter = 2
        
        self.dentries = {
            "d_root": {
                "id": "d_root",
                "name": "/",
                "parent_id": None,
                "inode_id": 1,
                "seq": 0,
                "is_negative": False,
                "children": {}
            }
        }
        self.dentry_counter = 1
        self.negative_lru = []
        self.query_history = set()
        
        self.stats = {
            "lookups_total": 0,
            "rcu_walk_success": 0,
            "rcu_walk_fallback_unlazy": 0,
            "positive_dentry_hits": 0,
            "negative_dentry_hits": 0,
            "negative_dentries_created": 0,
            "negative_dentries_pruned": 0
        }

    def create_file(self, path, is_dir=False):
        parts = [p for p in path.strip("/").split("/") if p]
        cur_dentry = self.dentries["d_root"]
        
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            cur_dentry["seq"] += 1
            
            if part in cur_dentry["children"]:
                child_id = cur_dentry["children"][part]
                child = self.dentries[child_id]
                if is_last:
                    if child["is_negative"]:
                        ino = self.inode_counter
                        self.inode_counter += 1
                        self.inodes[ino] = {"type": "DIR" if is_dir else "FILE", "name": part}
                        child["inode_id"] = ino
                        child["is_negative"] = False
                        child["seq"] += 1
                        if child_id in self.negative_lru:
                            self.negative_lru.remove(child_id)
                    return child
                cur_dentry = child
            else:
                ino = self.inode_counter
                self.inode_counter += 1
                self.inodes[ino] = {"type": "DIR" if (not is_last or is_dir) else "FILE", "name": part}
                
                new_id = f"d_{self.dentry_counter}"
                self.dentry_counter += 1
                new_d = {
                    "id": new_id,
                    "name": part,
                    "parent_id": cur_dentry["id"],
                    "inode_id": ino,
                    "seq": 0,
                    "is_negative": False,
                    "children": {}
                }
                self.dentries[new_id] = new_d
                cur_dentry["children"][part] = new_id
                cur_dentry = new_d
                
        return cur_dentry

    def lookup_path(self, path, mode="RCU_WALK", concurrent_seq_change=None):
        self.stats["lookups_total"] += 1
        parts = [p for p in path.strip("/").split("/") if p]
        
        cur = self.dentries["d_root"]
        walked_dent_ids = [cur["id"]]
        unlazy_triggered = False
        
        for i, part in enumerate(parts):
            if mode == "RCU_WALK" and concurrent_seq_change and cur["id"] in concurrent_seq_change:
                unlazy_triggered = True
                mode = "REF_WALK"
                self.stats["rcu_walk_fallback_unlazy"] += 1
                
            if part in cur["children"]:
                child_id = cur["children"][part]
                child = self.dentries[child_id]
                walked_dent_ids.append(child_id)
                
                if child["is_negative"]:
                    self.stats["negative_dentry_hits"] += 1
                    if child_id in self.negative_lru:
                        self.negative_lru.remove(child_id)
                        self.negative_lru.append(child_id)
                        
                    if mode == "RCU_WALK" and not unlazy_triggered:
                        self.stats["rcu_walk_success"] += 1
                        
                    return {
                        "path": path,
                        "found": False,
                        "inode_id": None,
                        "hit_type": "NEGATIVE_DENTRY_HIT",
                        "final_dentry": child_id,
                        "walked_dentries": walked_dent_ids,
                        "unlazy_fallback": unlazy_triggered
                    }
                else:
                    self.stats["positive_dentry_hits"] += 1
                    cur = child
            else:
                create_neg = True
                if self.bloom_guard:
                    if path not in self.query_history:
                        self.query_history.add(path)
                        create_neg = False
                        
                neg_id = None
                if create_neg:
                    cur["seq"] += 1
                    neg_id = f"d_{self.dentry_counter}"
                    self.dentry_counter += 1
                    neg_d = {
                        "id": neg_id,
                        "name": part,
                        "parent_id": cur["id"],
                        "inode_id": None,
                        "seq": 0,
                        "is_negative": True,
                        "children": {}
                    }
                    self.dentries[neg_id] = neg_d
                    cur["children"][part] = neg_id
                    self.negative_lru.append(neg_id)
                    self.stats["negative_dentries_created"] += 1
                    walked_dent_ids.append(neg_id)
                    
                    self._check_and_shrink_negative()
                    
                if mode == "RCU_WALK" and not unlazy_triggered:
                    self.stats["rcu_walk_success"] += 1
                    
                return {
                    "path": path,
                    "found": False,
                    "inode_id": None,
                    "hit_type": "NEGATIVE_DENTRY_CREATED" if create_neg else "COLD_MISS_NOT_CACHED",
                    "final_dentry": neg_id if create_neg else None,
                    "walked_dentries": walked_dent_ids,
                    "unlazy_fallback": unlazy_triggered
                }
                
        if mode == "RCU_WALK" and not unlazy_triggered:
            self.stats["rcu_walk_success"] += 1
            
        return {
            "path": path,
            "found": True,
            "inode_id": cur["inode_id"],
            "hit_type": "POSITIVE_DENTRY_HIT",
            "final_dentry": cur["id"],
            "walked_dentries": walked_dent_ids,
            "unlazy_fallback": unlazy_triggered
        }

    def unlink_file(self, path):
        parts = [p for p in path.strip("/").split("/") if p]
        cur = self.dentries["d_root"]
        
        for part in parts:
            if part in cur["children"]:
                child_id = cur["children"][part]
                cur = self.dentries[child_id]
            else:
                return {"status": "NOT_FOUND"}
                
        if cur["is_negative"]:
            return {"status": "ALREADY_NEGATIVE"}
            
        cur["inode_id"] = None
        cur["is_negative"] = True
        cur["seq"] += 1
        
        if cur["id"] not in self.negative_lru:
            self.negative_lru.append(cur["id"])
            
        self._check_and_shrink_negative()
        return {"status": "UNLINKED_TO_NEGATIVE", "dentry_id": cur["id"]}

    def _check_and_shrink_negative(self):
        while len(self.negative_lru) > self.max_negative:
            oldest_id = self.negative_lru.pop(0)
            self._prune_dentry(oldest_id)
            self.stats["negative_dentries_pruned"] += 1

    def _prune_dentry(self, dentry_id):
        if dentry_id not in self.dentries:
            return
        d = self.dentries.pop(dentry_id)
        parent_id = d["parent_id"]
        if parent_id in self.dentries:
            parent = self.dentries[parent_id]
            if d["name"] in parent["children"]:
                del parent["children"][d["name"]]
                parent["seq"] += 1

    def shrink_dcache(self, count=None):
        pruned = 0
        to_prune = count if count is not None else len(self.negative_lru)
        while self.negative_lru and pruned < to_prune:
            oldest_id = self.negative_lru.pop(0)
            self._prune_dentry(oldest_id)
            pruned += 1
            self.stats["negative_dentries_pruned"] += 1
        return pruned

    def get_snapshot(self):
        pos_dents = [d["id"] for d in self.dentries.values() if not d["is_negative"]]
        neg_dents = [d["id"] for d in self.dentries.values() if d["is_negative"]]
        return {
            "total_dentries": len(self.dentries),
            "positive_dentries_count": len(pos_dents),
            "negative_dentries_count": len(neg_dents),
            "negative_lru_order": list(self.negative_lru),
            "metrics": dict(self.stats)
        }

def run_simulation(req):
    cfg = req.get("config", {})
    engine = VfsDentryEngine(
        max_negative_dentries=cfg.get("max_negative_dentries", 16),
        bloom_guard=cfg.get("bloom_guard", False)
    )
    
    logs = []
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "CREATE_FILE":
            path = op_item["path"]
            is_dir = op_item.get("is_dir", False)
            dent = engine.create_file(path, is_dir)
            logs.append({
                "step": step,
                "op": op,
                "path": path,
                "dentry_id": dent["id"],
                "inode_id": dent["inode_id"],
                "is_dir": is_dir
            })
            
        elif op == "LOOKUP_PATH":
            path = op_item["path"]
            mode = op_item.get("mode", "RCU_WALK")
            seq_change = op_item.get("concurrent_seq_change", None)
            res = engine.lookup_path(path, mode, seq_change)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "UNLINK_FILE":
            path = op_item["path"]
            res = engine.unlink_file(path)
            logs.append({"step": step, "op": op, "path": path, **res})
            
        elif op == "SHRINK_DCACHE":
            count = op_item.get("count", None)
            pruned = engine.shrink_dcache(count)
            logs.append({"step": step, "op": op, "pruned_count": pruned})
            
        elif op == "GET_SNAPSHOT":
            snap = engine.get_snapshot()
            logs.append({"step": step, "op": op, "snapshot": snap})
            
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
