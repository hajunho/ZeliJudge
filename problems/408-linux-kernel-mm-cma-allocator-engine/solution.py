import sys
import json
import math

class Page:
    def __init__(self, pfn, pool="CMA"):
        self.pfn = pfn
        self.pool = pool
        self.is_free = True
        self.owner = None
        self.is_pinned = False
        self.data_id = None
        self.dma_alloc_id = None

class PageBlock:
    def __init__(self, block_id, start_pfn, size_pages):
        self.block_id = block_id
        self.start_pfn = start_pfn
        self.size_pages = size_pages
        self.migratetype = "MIGRATE_CMA"

class CMASimulation:
    def __init__(self, config):
        self.cma_base_pfn = config.get("cma_base_pfn", 2048)
        self.cma_size_pages = config.get("cma_size_pages", 256)
        self.pageblock_size = config.get("pageblock_size", 64)
        self.buddy_movable_capacity = config.get("buddy_movable_capacity", 512)
        self.buddy_unmovable_capacity = config.get("buddy_unmovable_capacity", 256)
        
        self.cma_pages = [Page(self.cma_base_pfn + i, "CMA") for i in range(self.cma_size_pages)]
        self.pageblocks = []
        num_blocks = self.cma_size_pages // self.pageblock_size
        for i in range(num_blocks):
            pb = PageBlock(i, self.cma_base_pfn + i * self.pageblock_size, self.pageblock_size)
            self.pageblocks.append(pb)
            
        self.buddy_movable_free = self.buddy_movable_capacity
        self.buddy_unmovable_free = self.buddy_unmovable_capacity
        self.buddy_pages = {}
        
        self.dma_allocs = {}
        self.cma_alloc_success = 0
        self.cma_alloc_failures = 0
        self.total_migrated_pages = 0
        self.op_logs = []

    def get_cma_page(self, pfn):
        idx = pfn - self.cma_base_pfn
        if 0 <= idx < self.cma_size_pages:
            return self.cma_pages[idx]
        return None

    def get_pageblocks_for_range(self, start_pfn, count):
        blocks = []
        end_pfn = start_pfn + count - 1
        for pb in self.pageblocks:
            pb_end = pb.start_pfn + pb.size_pages - 1
            if not (end_pfn < pb.start_pfn or start_pfn > pb_end):
                blocks.append(pb)
        return blocks

    def alloc_general(self, count, alloc_type, is_pinned=False, data_ids=None):
        if data_ids is None:
            data_ids = [f"dat_{len(self.buddy_pages) + i}" for i in range(count)]
            
        if alloc_type == "UNMOVABLE":
            if self.buddy_unmovable_free < count:
                return {"status": "ENOMEM", "allocated": 0}
            self.buddy_unmovable_free -= count
            for d in data_ids:
                self.buddy_pages[d] = {"pool": "BUDDY_UNMOVABLE", "is_pinned": is_pinned}
            return {"status": "SUCCESS", "pool": "BUDDY_UNMOVABLE", "allocated": count}
        else:
            allocated_from_buddy = min(self.buddy_movable_free, count)
            remaining = count - allocated_from_buddy
            
            cma_free_indices = [
                i for i, p in enumerate(self.cma_pages)
                if p.is_free and self.pageblocks[i // self.pageblock_size].migratetype == "MIGRATE_CMA"
            ]
            
            if len(cma_free_indices) < remaining:
                return {"status": "ENOMEM", "allocated": 0}
                
            self.buddy_movable_free -= allocated_from_buddy
            for i in range(allocated_from_buddy):
                d = data_ids[i]
                self.buddy_pages[d] = {"pool": "BUDDY_MOVABLE", "is_pinned": is_pinned}
                
            for i in range(remaining):
                d = data_ids[allocated_from_buddy + i]
                c_idx = cma_free_indices[i]
                p = self.cma_pages[c_idx]
                p.is_free = False
                p.owner = "PAGE_CACHE"
                p.is_pinned = is_pinned
                p.data_id = d
                
            return {
                "status": "SUCCESS",
                "allocated_buddy": allocated_from_buddy,
                "allocated_cma": remaining,
                "total": count
            }

    def free_general(self, data_id):
        if data_id in self.buddy_pages:
            info = self.buddy_pages.pop(data_id)
            if info["pool"] == "BUDDY_UNMOVABLE":
                self.buddy_unmovable_free += 1
            else:
                self.buddy_movable_free += 1
            return True
            
        for p in self.cma_pages:
            if p.data_id == data_id:
                p.is_free = True
                p.owner = None
                p.is_pinned = False
                p.data_id = None
                return True
        return False

    def pin_page(self, data_id, pin_state=True):
        if data_id in self.buddy_pages:
            self.buddy_pages[data_id]["is_pinned"] = pin_state
            return True
        for p in self.cma_pages:
            if p.data_id == data_id:
                p.is_pinned = pin_state
                return True
        return False

    def cma_alloc(self, alloc_id, count, align_order=0):
        alignment = 1 << align_order
        found_start_idx = None
        for i in range(0, self.cma_size_pages - count + 1, alignment):
            pfn = self.cma_base_pfn + i
            if pfn % alignment != 0:
                continue
            
            collision = False
            for j in range(count):
                if self.cma_pages[i + j].owner == "DMA":
                    collision = True
                    break
            if not collision:
                found_start_idx = i
                break
                
        if found_start_idx is None:
            self.cma_alloc_failures += 1
            return {"status": "CMA_ERR_NO_CONTIGUOUS_SPACE"}
            
        start_pfn = self.cma_base_pfn + found_start_idx
        target_pages = [self.cma_pages[found_start_idx + j] for j in range(count)]
        affected_blocks = self.get_pageblocks_for_range(start_pfn, count)
        
        old_block_types = [pb.migratetype for pb in affected_blocks]
        for pb in affected_blocks:
            pb.migratetype = "MIGRATE_ISOLATE"
            
        pages_to_migrate = [p for p in target_pages if not p.is_free and p.owner != "DMA"]
        
        for p in pages_to_migrate:
            if p.is_pinned:
                for idx, pb in enumerate(affected_blocks):
                    pb.migratetype = old_block_types[idx]
                self.cma_alloc_failures += 1
                return {
                    "status": "CMA_ERR_PINNED_PAGE_COLLISION",
                    "failed_pfn": p.pfn,
                    "failed_data_id": p.data_id
                }
                
        if self.buddy_movable_free < len(pages_to_migrate):
            for idx, pb in enumerate(affected_blocks):
                pb.migratetype = old_block_types[idx]
            self.cma_alloc_failures += 1
            return {
                "status": "CMA_ERR_MIGRATION_NO_MEM",
                "needed": len(pages_to_migrate),
                "available": self.buddy_movable_free
            }
            
        for p in pages_to_migrate:
            data_id = p.data_id
            self.buddy_movable_free -= 1
            self.buddy_pages[data_id] = {"pool": "BUDDY_MOVABLE", "is_pinned": False}
            p.is_free = True
            p.owner = None
            p.data_id = None
            self.total_migrated_pages += 1
            
        for p in target_pages:
            p.is_free = False
            p.owner = "DMA"
            p.dma_alloc_id = alloc_id
            
        self.dma_allocs[alloc_id] = (start_pfn, count)
        self.cma_alloc_success += 1
        return {
            "status": "SUCCESS",
            "start_pfn": start_pfn,
            "count": count,
            "migrated_count": len(pages_to_migrate)
        }

    def cma_release(self, alloc_id):
        if alloc_id not in self.dma_allocs:
            return {"status": "NOT_FOUND"}
            
        start_pfn, count = self.dma_allocs.pop(alloc_id)
        start_idx = start_pfn - self.cma_base_pfn
        for j in range(count):
            p = self.cma_pages[start_idx + j]
            p.is_free = True
            p.owner = None
            p.dma_alloc_id = None
            
        affected_blocks = self.get_pageblocks_for_range(start_pfn, count)
        for pb in affected_blocks:
            pb_start_idx = pb.start_pfn - self.cma_base_pfn
            has_other_dma = False
            for k in range(pb.size_pages):
                if self.cma_pages[pb_start_idx + k].owner == "DMA":
                    has_other_dma = True
                    break
            if not has_other_dma:
                pb.migratetype = "MIGRATE_CMA"
                
        return {"status": "SUCCESS", "freed_pfn": start_pfn, "count": count}

    def run(self, operations):
        for op in operations:
            kind = op["op"]
            if kind == "ALLOC_GENERAL":
                res = self.alloc_general(
                    op["count"],
                    op["type"],
                    is_pinned=op.get("is_pinned", False),
                    data_ids=op.get("data_ids", None)
                )
                self.op_logs.append({"op": kind, "result": res})
            elif kind == "FREE_GENERAL":
                res = self.free_general(op["data_id"])
                self.op_logs.append({"op": kind, "result": res})
            elif kind == "PIN_PAGE":
                res = self.pin_page(op["data_id"], pin_state=op.get("is_pinned", True))
                self.op_logs.append({"op": kind, "result": res})
            elif kind == "CMA_ALLOC":
                res = self.cma_alloc(
                    op["alloc_id"],
                    op["count"],
                    align_order=op.get("align_order", 0)
                )
                self.op_logs.append({"op": kind, "alloc_id": op["alloc_id"], "result": res})
            elif kind == "CMA_RELEASE":
                res = self.cma_release(op["alloc_id"])
                self.op_logs.append({"op": kind, "alloc_id": op["alloc_id"], "result": res})
                
        return self.generate_result()

    def generate_result(self):
        cma_free = sum(1 for p in self.cma_pages if p.is_free)
        cma_dma = sum(1 for p in self.cma_pages if p.owner == "DMA")
        cma_movable = sum(1 for p in self.cma_pages if p.owner in ("PAGE_CACHE", "ANON"))
        
        pb_states = {}
        for pb in self.pageblocks:
            pb_states[f"block_{pb.block_id}"] = {
                "start_pfn": pb.start_pfn,
                "migratetype": pb.migratetype
            }
            
        dma_active = {}
        for alloc_id, (start_pfn, count) in self.dma_allocs.items():
            dma_active[alloc_id] = {"start_pfn": start_pfn, "count": count}
            
        return {
            "summary": {
                "cma_alloc_success": self.cma_alloc_success,
                "cma_alloc_failures": self.cma_alloc_failures,
                "total_migrated_pages": self.total_migrated_pages,
                "cma_free_pages": cma_free,
                "cma_dma_allocated_pages": cma_dma,
                "cma_movable_pages": cma_movable,
                "buddy_movable_free": self.buddy_movable_free,
                "buddy_unmovable_free": self.buddy_unmovable_free
            },
            "pageblocks": pb_states,
            "dma_allocations": dma_active,
            "operation_logs": self.op_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])
    
    sim = CMASimulation(config)
    result = sim.run(operations)
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
