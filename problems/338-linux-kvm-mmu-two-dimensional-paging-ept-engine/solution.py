# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #338: Linux Kernel KVM x86 Two-Dimensional Paging (EPT) Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class KvmEptMmuEngine:
    def __init__(self, config):
        self.hugepage_support = config.get("hugepage_support", True)
        self.memslots = {}
        for s in config.get("memslots", []):
            slot_id = s["slot_id"]
            self.memslots[slot_id] = {
                "slot_id": slot_id,
                "base_gpa": int(s["base_gpa"], 16) if isinstance(s["base_gpa"], str) else s["base_gpa"],
                "size": int(s["size"], 16) if isinstance(s["size"], str) else s["size"],
                "base_hva": int(s["base_hva"], 16) if isinstance(s["base_hva"], str) else s["base_hva"],
                "base_hpa": int(s["base_hpa"], 16) if isinstance(s["base_hpa"], str) else s["base_hpa"],
                "flags": set(s.get("flags", [])),
                "dirty_bitmap": {}
            }
        self.tables = {}
        self.next_table_id = 1
        self.root_table_id = self._alloc_table(4)
        
        self.stats = {
            "ept_hits": 0,
            "ept_violations": 0,
            "fast_pf_count": 0,
            "slow_pf_count": 0,
            "mmio_count": 0,
            "invept_count": 0,
            "allocated_tables": 1,
            "freed_tables": 0
        }

    def _alloc_table(self, level):
        tid = self.next_table_id
        self.next_table_id += 1
        self.tables[tid] = {
            "level": level,
            "entries": {}
        }
        return tid

    def _find_memslot(self, gpa):
        for slot in self.memslots.values():
            if slot["base_gpa"] <= gpa < slot["base_gpa"] + slot["size"]:
                return slot
        return None

    def _split_gpa(self, gpa):
        idx4 = (gpa >> 39) & 0x1FF
        idx3 = (gpa >> 30) & 0x1FF
        idx2 = (gpa >> 21) & 0x1FF
        idx1 = (gpa >> 12) & 0x1FF
        offset = gpa & 0xFFF
        return idx4, idx3, idx2, idx1, offset

    def _walk_ept(self, gpa):
        idx4, idx3, idx2, idx1, offset = self._split_gpa(gpa)
        indices = [None, idx1, idx2, idx3, idx4]
        
        curr_tid = self.root_table_id
        path = []
        
        for level in range(4, 0, -1):
            idx = indices[level]
            table = self.tables[curr_tid]
            spte = table["entries"].get(idx)
            path.append((curr_tid, level, idx, spte))
            if not spte:
                return path, None
            if spte.get("is_leaf", False):
                return path, spte
            curr_tid = spte["child_table_id"]
        return path, None

    def guest_access(self, gpa, access_type, allow_hugepage=False):
        idx4, idx3, idx2, idx1, offset = self._split_gpa(gpa)
        path, leaf_spte = self._walk_ept(gpa)
        
        req_read = (access_type == "READ")
        req_write = (access_type == "WRITE")
        req_exec = (access_type == "EXEC")

        if leaf_spte:
            perm_ok = True
            if req_read and not leaf_spte["read"]:
                perm_ok = False
            if req_write and not leaf_spte["write"]:
                perm_ok = False
            if req_exec and not leaf_spte["exec"]:
                perm_ok = False
            
            if perm_ok:
                self.stats["ept_hits"] += 1
                leaf_spte["accessed"] = True
                if req_write:
                    leaf_spte["dirty"] = True
                hpa = leaf_spte["base_hpa"] + (offset if not leaf_spte["is_huge"] else (gpa & 0x1FFFFF))
                return {
                    "status": "HIT",
                    "gpa": hex(gpa),
                    "hpa": hex(hpa),
                    "level": leaf_spte["level"],
                    "is_huge": leaf_spte["is_huge"],
                    "accessed": leaf_spte["accessed"],
                    "dirty": leaf_spte["dirty"]
                }
            
            self.stats["ept_violations"] += 1
            slot = self._find_memslot(gpa)
            if not slot:
                self.stats["mmio_count"] += 1
                return {"status": "MMIO_FAULT", "gpa": hex(gpa), "access_type": access_type}

            if req_write and not leaf_spte["write"]:
                if "READONLY" in slot["flags"]:
                    return {"status": "PERM_DENIED_READONLY", "gpa": hex(gpa)}
                
                if "DIRTY_LOG_TRACKING" in slot["flags"]:
                    page_idx = (gpa - slot["base_gpa"]) >> 12
                    slot["dirty_bitmap"][page_idx] = True
                    leaf_spte["write"] = True
                    leaf_spte["accessed"] = True
                    leaf_spte["dirty"] = True
                    self.stats["fast_pf_count"] += 1
                    hpa = leaf_spte["base_hpa"] + (offset if not leaf_spte["is_huge"] else (gpa & 0x1FFFFF))
                    return {
                        "status": "FAST_PF_DIRTY_LOG",
                        "gpa": hex(gpa),
                        "hpa": hex(hpa),
                        "dirty_marked_page": page_idx
                    }

        self.stats["ept_violations"] += 1
        slot = self._find_memslot(gpa)
        if not slot:
            self.stats["mmio_count"] += 1
            return {"status": "MMIO_EMULATION", "gpa": hex(gpa), "access_type": access_type}
        
        self.stats["slow_pf_count"] += 1
        indices = [None, idx1, idx2, idx3, idx4]
        curr_tid = self.root_table_id
        allocated_in_pf = 0
        
        can_use_huge = (self.hugepage_support and allow_hugepage and
                        ((gpa & 0x1FFFFF) == 0 or (slot["size"] >= 0x200000 and (slot["base_gpa"] & 0x1FFFFF) == 0)))
        target_leaf_level = 2 if can_use_huge else 1

        for level in range(4, target_leaf_level, -1):
            idx = indices[level]
            table = self.tables[curr_tid]
            if idx not in table["entries"]:
                new_tid = self._alloc_table(level - 1)
                self.stats["allocated_tables"] += 1
                allocated_in_pf += 1
                table["entries"][idx] = {
                    "is_leaf": False,
                    "child_table_id": new_tid,
                    "read": True,
                    "write": True,
                    "exec": True,
                    "level": level
                }
            curr_tid = table["entries"][idx]["child_table_id"]

        leaf_idx = indices[target_leaf_level]
        leaf_table = self.tables[curr_tid]
        
        page_mask = 0x1FFFFF if target_leaf_level == 2 else 0xFFF
        base_hpa = slot["base_hpa"] + ((gpa & ~page_mask) - slot["base_gpa"])
        
        is_ro = "READONLY" in slot["flags"]
        is_dirty_track = "DIRTY_LOG_TRACKING" in slot["flags"]
        
        write_perm = False if (is_ro or is_dirty_track) else True
        if req_write and is_dirty_track and not is_ro:
            page_idx = (gpa - slot["base_gpa"]) >> 12
            slot["dirty_bitmap"][page_idx] = True
            write_perm = True

        leaf_spte = {
            "is_leaf": True,
            "level": target_leaf_level,
            "is_huge": (target_leaf_level == 2),
            "base_hpa": base_hpa,
            "read": True,
            "write": write_perm,
            "exec": True,
            "accessed": True,
            "dirty": req_write
        }
        leaf_table["entries"][leaf_idx] = leaf_spte
        hpa = base_hpa + (gpa & page_mask)

        return {
            "status": "PAGE_FAULT_RESOLVED",
            "gpa": hex(gpa),
            "hpa": hex(hpa),
            "level": target_leaf_level,
            "is_huge": (target_leaf_level == 2),
            "write_perm": write_perm,
            "tables_allocated": allocated_in_pf
        }

    def flush_dirty_log(self, slot_id):
        slot = self.memslots.get(slot_id)
        if not slot:
            return {"error": "INVALID_SLOT"}
        dirty_pages = sorted(list(slot["dirty_bitmap"].keys()))
        slot["dirty_bitmap"].clear()
        
        wp_count = 0
        def wp_table(tid):
            nonlocal wp_count
            table = self.tables[tid]
            for spte in table["entries"].values():
                if spte["is_leaf"]:
                    if slot["base_hpa"] <= spte["base_hpa"] < slot["base_hpa"] + slot["size"]:
                        if spte["write"]:
                            spte["write"] = False
                            wp_count += 1
                else:
                    wp_table(spte["child_table_id"])
        
        wp_table(self.root_table_id)
        self.stats["invept_count"] += 1
        return {
            "slot_id": slot_id,
            "dirty_pages_count": len(dirty_pages),
            "dirty_pages": dirty_pages[:20],
            "write_protected_sptes": wp_count
        }

    def invept(self, invept_type="SINGLE_CONTEXT"):
        self.stats["invept_count"] += 1
        return {"status": "TLB_FLUSHED", "type": invept_type}

    def unmap_memslot(self, slot_id):
        slot = self.memslots.get(slot_id)
        if not slot:
            return {"error": "INVALID_SLOT"}
        
        zapped_sptes = 0
        freed_tables = 0
        
        def prune_table(tid):
            nonlocal zapped_sptes, freed_tables
            table = self.tables[tid]
            keys_to_del = []
            for idx, spte in table["entries"].items():
                if spte["is_leaf"]:
                    if slot["base_hpa"] <= spte["base_hpa"] < slot["base_hpa"] + slot["size"]:
                        keys_to_del.append(idx)
                        zapped_sptes += 1
                else:
                    child_tid = spte["child_table_id"]
                    prune_table(child_tid)
                    if len(self.tables[child_tid]["entries"]) == 0:
                        keys_to_del.append(idx)
                        del self.tables[child_tid]
                        freed_tables += 1
                        self.stats["freed_tables"] += 1
            for k in keys_to_del:
                del table["entries"][k]

        prune_table(self.root_table_id)
        del self.memslots[slot_id]
        self.stats["invept_count"] += 1
        return {
            "status": "MEMSLOT_UNMAPPED",
            "slot_id": slot_id,
            "zapped_sptes": zapped_sptes,
            "freed_tables": freed_tables
        }

    def get_stats(self):
        active_tables = len(self.tables)
        total_leafs = 0
        for table in self.tables.values():
            for spte in table["entries"].values():
                if spte["is_leaf"]:
                    total_leafs += 1
        return {
            **self.stats,
            "active_tables": active_tables,
            "total_leaf_sptes": total_leafs
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    
    engine = KvmEptMmuEngine(data["config"])
    results = []
    for op in data["operations"]:
        opcode = op["op"]
        if opcode == "ACCESS":
            gpa = int(op["gpa"], 16) if isinstance(op["gpa"], str) else op["gpa"]
            access_type = op["access_type"]
            allow_huge = op.get("hugepage", False)
            res = engine.guest_access(gpa, access_type, allow_huge)
            results.append(res)
        elif opcode == "INVEPT":
            res = engine.invept(op.get("type", "SINGLE_CONTEXT"))
            results.append(res)
        elif opcode == "FLUSH_DIRTY_LOG":
            res = engine.flush_dirty_log(op["slot_id"])
            results.append(res)
        elif opcode == "UNMAP_MEMSLOT":
            res = engine.unmap_memslot(op["slot_id"])
            results.append(res)
    
    stats = engine.get_stats()
    output = {
        "results": results,
        "mmu_stats": stats,
        "summary": {
            "memslot_count": len(engine.memslots),
            "status": "HEALTHY"
        }
    }
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
