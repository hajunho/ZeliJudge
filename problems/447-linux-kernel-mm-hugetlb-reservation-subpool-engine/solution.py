import sys
import json

class ResvMap:
    def __init__(self):
        self.regions = []

    def count_in_range(self, start, end):
        cnt = 0
        for s, e in self.regions:
            ov_s = max(start, s)
            ov_e = min(end, e)
            if ov_s < ov_e:
                cnt += (ov_e - ov_s)
        return cnt

    def add_range(self, start, end):
        existing = self.count_in_range(start, end)
        needed = (end - start) - existing

        all_regs = sorted(self.regions + [[start, end]], key=lambda x: x[0])
        merged = []
        for r in all_regs:
            if not merged:
                merged.append(r)
            else:
                prev = merged[-1]
                if r[0] <= prev[1]:
                    prev[1] = max(prev[1], r[1])
                else:
                    merged.append(r)
        self.regions = merged
        return needed

    def consume_page(self, page_idx):
        for i, (s, e) in enumerate(self.regions):
            if s <= page_idx < e:
                if s == page_idx and e == page_idx + 1:
                    self.regions.pop(i)
                elif s == page_idx:
                    self.regions[i][0] = page_idx + 1
                elif e == page_idx + 1:
                    self.regions[i][1] = page_idx
                else:
                    self.regions[i][1] = page_idx
                    self.regions.insert(i + 1, [page_idx + 1, e])
                return True
        return False

    def remove_range(self, start, end):
        removed_cnt = self.count_in_range(start, end)
        new_regs = []
        for s, e in self.regions:
            ov_s = max(start, s)
            ov_e = min(end, e)
            if ov_s >= ov_e:
                new_regs.append([s, e])
            else:
                if s < ov_s:
                    new_regs.append([s, ov_s])
                if ov_e < e:
                    new_regs.append([ov_e, e])
        self.regions = new_regs
        return removed_cnt


class HugeTlbEngine:
    def __init__(self, config):
        self.total_pages = config.get("total_pages", 100)
        self.free_pages = self.total_pages
        self.resv_pages = 0
        
        self.subpools = {}
        for sp in config.get("subpools", []):
            sp_id = sp["id"]
            self.subpools[sp_id] = {
                "max_pages": sp.get("max_pages", -1),
                "used_pages": 0,
                "rsv_pages": 0
            }
        
        if "default" not in self.subpools:
            self.subpools["default"] = {"max_pages": -1, "used_pages": 0, "rsv_pages": 0}
            
        self.vmas = {}
        self.sigbus_count = 0

    def create_vma(self, vma_id, subpool_id="default"):
        if subpool_id not in self.subpools:
            return {"status": "ERROR_UNKNOWN_SUBPOOL", "subpool_id": subpool_id}
        if vma_id in self.vmas:
            return {"status": "ERROR_VMA_EXISTS", "vma_id": vma_id}
        self.vmas[vma_id] = {
            "subpool_id": subpool_id,
            "resv_map": ResvMap(),
            "allocated_pages": set()
        }
        return {"status": "VMA_CREATED", "vma_id": vma_id, "subpool_id": subpool_id}

    def reserve_pages(self, vma_id, start_idx, end_idx):
        if vma_id not in self.vmas:
            return {"status": "ERROR_VMA_NOT_FOUND", "vma_id": vma_id}
        
        vma = self.vmas[vma_id]
        sp = self.subpools[vma["subpool_id"]]
        
        existing_resv = vma["resv_map"].count_in_range(start_idx, end_idx)
        already_allocated = sum(1 for p in range(start_idx, end_idx) if p in vma["allocated_pages"])
        needed = (end_idx - start_idx) - existing_resv - already_allocated
        if needed < 0:
            needed = 0

        if sp["max_pages"] != -1:
            if sp["used_pages"] + sp["rsv_pages"] + needed > sp["max_pages"]:
                return {"status": "ENOMEM", "reason": "SUBPOOL_QUOTA_EXCEEDED", "needed": needed}

        unresv_free = self.free_pages - self.resv_pages
        if unresv_free < needed:
            return {"status": "ENOMEM", "reason": "GLOBAL_POOL_EXHAUSTED", "needed": needed}

        vma["resv_map"].add_range(start_idx, end_idx)
        sp["rsv_pages"] += needed
        self.resv_pages += needed

        return {"status": "RESERVED", "vma_id": vma_id, "start": start_idx, "end": end_idx, "reserved_pages": needed}

    def page_fault(self, vma_id, page_idx):
        if vma_id not in self.vmas:
            return {"status": "ERROR_VMA_NOT_FOUND", "vma_id": vma_id}
        
        vma = self.vmas[vma_id]
        sp = self.subpools[vma["subpool_id"]]
        
        if page_idx in vma["allocated_pages"]:
            return {"status": "ALREADY_PRESENT", "vma_id": vma_id, "page_idx": page_idx}

        has_resv = vma["resv_map"].consume_page(page_idx)
        if has_resv:
            sp["rsv_pages"] -= 1
            sp["used_pages"] += 1
            self.resv_pages -= 1
            self.free_pages -= 1
            vma["allocated_pages"].add(page_idx)
            return {"status": "FAULT_SUCCESS", "vma_id": vma_id, "page_idx": page_idx, "from_reservation": True}
        else:
            if sp["max_pages"] != -1 and (sp["used_pages"] + sp["rsv_pages"] + 1 > sp["max_pages"]):
                self.sigbus_count += 1
                return {"status": "SIGBUS", "vma_id": vma_id, "page_idx": page_idx, "reason": "SUBPOOL_QUOTA_EXCEEDED"}

            unresv_free = self.free_pages - self.resv_pages
            if unresv_free < 1:
                self.sigbus_count += 1
                return {"status": "SIGBUS", "vma_id": vma_id, "page_idx": page_idx, "reason": "NO_UNRESERVED_HUGEPAGE"}

            sp["used_pages"] += 1
            self.free_pages -= 1
            vma["allocated_pages"].add(page_idx)
            return {"status": "FAULT_SUCCESS", "vma_id": vma_id, "page_idx": page_idx, "from_reservation": False}

    def unmap_pages(self, vma_id, start_idx, end_idx):
        if vma_id not in self.vmas:
            return {"status": "ERROR_VMA_NOT_FOUND", "vma_id": vma_id}
        
        vma = self.vmas[vma_id]
        sp = self.subpools[vma["subpool_id"]]

        freed_phys = 0
        for p in list(vma["allocated_pages"]):
            if start_idx <= p < end_idx:
                vma["allocated_pages"].remove(p)
                sp["used_pages"] -= 1
                self.free_pages += 1
                freed_phys += 1

        freed_resv = vma["resv_map"].remove_range(start_idx, end_idx)
        sp["rsv_pages"] -= freed_resv
        self.resv_pages -= freed_resv

        return {
            "status": "UNMAPPED",
            "vma_id": vma_id,
            "start": start_idx,
            "end": end_idx,
            "freed_physical": freed_phys,
            "freed_resv": freed_resv
        }

    def resize_pool(self, new_total):
        allocated = self.total_pages - self.free_pages
        min_allowable = allocated + self.resv_pages
        if new_total < min_allowable:
            return {"status": "EBUSY", "min_allowable": min_allowable, "attempted": new_total}

        delta = new_total - self.total_pages
        self.total_pages = new_total
        self.free_pages += delta
        return {"status": "RESIZED", "total_pages": self.total_pages, "free_pages": self.free_pages}

    def query_stats(self):
        allocated = self.total_pages - self.free_pages
        sp_stats = {}
        for sp_id in sorted(self.subpools.keys()):
            sp = self.subpools[sp_id]
            sp_stats[sp_id] = {
                "max_pages": sp["max_pages"],
                "used_pages": sp["used_pages"],
                "rsv_pages": sp["rsv_pages"]
            }
        return {
            "global_total_pages": self.total_pages,
            "global_free_pages": self.free_pages,
            "global_resv_pages": self.resv_pages,
            "global_allocated_pages": allocated,
            "subpools": sp_stats,
            "sigbus_count": self.sigbus_count
        }

def solve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    
    input_data = json.loads(raw)
    config = input_data.get("config", {})
    engine = HugeTlbEngine(config)
    results = []
    
    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "CREATE_VMA":
            res = engine.create_vma(op["vma_id"], op.get("subpool_id", "default"))
            results.append(res)
        elif cmd == "RESERVE_PAGES":
            res = engine.reserve_pages(op["vma_id"], op["start"], op["end"])
            results.append(res)
        elif cmd == "PAGE_FAULT":
            res = engine.page_fault(op["vma_id"], op["page_idx"])
            results.append(res)
        elif cmd == "UNMAP_PAGES":
            res = engine.unmap_pages(op["vma_id"], op["start"], op["end"])
            results.append(res)
        elif cmd == "RESIZE_POOL":
            res = engine.resize_pool(op["new_total"])
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = engine.query_stats()
            results.append(res)
            
    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
