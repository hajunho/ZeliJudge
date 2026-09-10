import sys
import json

class SlabPage:
    def __init__(self, page_id, objects_per_slab):
        self.page_id = page_id
        self.objects = objects_per_slab
        self.inuse = 0
        self.frozen = False
        self.cpu_owner = None
        self.freelist = []
        for i in range(objects_per_slab):
            self.freelist.append(f"{page_id}-obj{i}")
        self.all_objects = set(self.freelist)

class SlubAllocator:
    def __init__(self, config):
        self.object_size = config.get("object_size", 64)
        self.objects_per_slab = config.get("objects_per_slab", 8)
        self.cpu_count = config.get("cpu_count", 4)
        self.cpu_partial_limit = config.get("cpu_partial_limit", 2)
        self.min_partial = config.get("min_partial", 1)

        self.next_slab_id = 1
        self.buddy_alloc_count = 0
        self.buddy_free_count = 0

        self.cpu_caches = {}
        for cpu in range(self.cpu_count):
            self.cpu_caches[cpu] = {
                "page": None,
                "freelist": [],
                "partial": []
            }

        self.node_partial = []
        self.node_lock_acquisitions = 0
        self.object_map = {}

        self.alloc_paths = {
            "fast_path_cpu": 0,
            "refill_from_page": 0,
            "cpu_partial": 0,
            "node_partial": 0,
            "buddy_alloc": 0
        }
        self.free_paths = {
            "fast_path_local": 0,
            "remote_frozen": 0,
            "unfreeze_to_partial": 0,
            "partial_freed": 0,
            "discard_empty_slab": 0
        }

    def _alloc_buddy_slab(self, for_cpu):
        page_id = f"slab-{self.next_slab_id}"
        self.next_slab_id += 1
        self.buddy_alloc_count += 1
        slab = SlabPage(page_id, self.objects_per_slab)
        for obj in slab.all_objects:
            self.object_map[obj] = slab
        return slab

    def alloc(self, cpu):
        c = self.cpu_caches[cpu]

        # Path 1: Fast Path from CPU freelist
        if c["page"] is not None and len(c["freelist"]) > 0:
            obj = c["freelist"].pop(0)
            c["page"].inuse += 1
            self.alloc_paths["fast_path_cpu"] += 1
            return {"allocated_obj": obj, "path": "FAST_PATH_CPU_FREELIST", "slab": c["page"].page_id}

        # Path 2: Refill from c->page.freelist (remote frees while active)
        if c["page"] is not None and len(c["page"].freelist) > 0:
            c["freelist"] = c["page"].freelist
            c["page"].freelist = []
            obj = c["freelist"].pop(0)
            c["page"].inuse += 1
            self.alloc_paths["refill_from_page"] += 1
            return {"allocated_obj": obj, "path": "SLOW_PATH_CPU_PAGE_REFILL", "slab": c["page"].page_id}

        # If c->page was present but completely full, unfreeze it as a full slab
        if c["page"] is not None:
            old_slab = c["page"]
            old_slab.frozen = False
            old_slab.cpu_owner = None
            c["page"] = None

        # Path 3: CPU Partial List
        if len(c["partial"]) > 0:
            slab = c["partial"].pop(0)
            slab.frozen = True
            slab.cpu_owner = cpu
            c["page"] = slab
            c["freelist"] = slab.freelist
            slab.freelist = []
            obj = c["freelist"].pop(0)
            slab.inuse += 1
            self.alloc_paths["cpu_partial"] += 1
            return {"allocated_obj": obj, "path": "SLOW_PATH_CPU_PARTIAL", "slab": slab.page_id}

        # Path 4: Node Partial List (requires node spinlock)
        self.node_lock_acquisitions += 1
        if len(self.node_partial) > 0:
            slab = self.node_partial.pop(0)
            slab.frozen = True
            slab.cpu_owner = cpu
            c["page"] = slab
            c["freelist"] = slab.freelist
            slab.freelist = []

            # Pre-fetch additional slabs from node partial to cpu partial up to cpu_partial_limit
            while len(c["partial"]) < self.cpu_partial_limit and len(self.node_partial) > 0:
                p_slab = self.node_partial.pop(0)
                p_slab.cpu_owner = cpu
                c["partial"].append(p_slab)

            obj = c["freelist"].pop(0)
            slab.inuse += 1
            self.alloc_paths["node_partial"] += 1
            return {"allocated_obj": obj, "path": "SLOW_PATH_NODE_PARTIAL", "slab": slab.page_id}

        # Path 5: Buddy Allocator Fallback
        slab = self._alloc_buddy_slab(cpu)
        slab.frozen = True
        slab.cpu_owner = cpu
        c["page"] = slab
        c["freelist"] = slab.freelist
        slab.freelist = []
        obj = c["freelist"].pop(0)
        slab.inuse += 1
        self.alloc_paths["buddy_alloc"] += 1
        return {"allocated_obj": obj, "path": "SLOW_PATH_BUDDY_ALLOC", "slab": slab.page_id}

    def free(self, cpu, obj_id):
        if obj_id not in self.object_map:
            return {"status": "ERROR", "reason": f"Unknown object {obj_id}"}

        slab = self.object_map[obj_id]
        c = self.cpu_caches[cpu]

        slab.inuse -= 1

        # Case 1: Fast Path Local Free (freed on the CPU that owns this active slab)
        if c["page"] is not None and c["page"] == slab:
            c["freelist"].insert(0, obj_id)
            self.free_paths["fast_path_local"] += 1
            return {"status": "OK", "path": "FAST_PATH_LOCAL_FREE", "slab": slab.page_id}

        # Case 2: Remote Free to Active / Frozen Slab (owned by another CPU)
        if slab.frozen:
            slab.freelist.append(obj_id)
            self.free_paths["remote_frozen"] += 1
            return {"status": "OK", "path": "SLOW_PATH_REMOTE_FREE_FROZEN", "slab": slab.page_id}

        # Case 3: Slab was full (frozen == False, not on any partial list) and now has 1 free object
        if not slab.frozen and slab not in self.node_partial and not any(slab in cc["partial"] for cc in self.cpu_caches.values()):
            slab.freelist.append(obj_id)
            self.node_lock_acquisitions += 1
            self.node_partial.append(slab)
            self.free_paths["unfreeze_to_partial"] += 1
            return {"status": "OK", "path": "SLOW_PATH_UNFREEZE_TO_PARTIAL", "slab": slab.page_id}

        # Case 4: Slab was already in a partial list
        slab.freelist.append(obj_id)
        self.free_paths["partial_freed"] += 1

        # Check if slab became completely empty
        if slab.inuse == 0:
            if slab in self.node_partial:
                if len(self.node_partial) > self.min_partial:
                    self.node_lock_acquisitions += 1
                    self.node_partial.remove(slab)
                    self.buddy_free_count += 1
                    self.free_paths["discard_empty_slab"] += 1
                    for o in slab.all_objects:
                        del self.object_map[o]
                    return {"status": "OK", "path": "SLOW_PATH_DISCARD_EMPTY_SLAB", "slab": slab.page_id}

        return {"status": "OK", "path": "SLOW_PATH_PARTIAL_FREED", "slab": slab.page_id}

    def unfreeze_cpu_slab(self, cpu):
        c = self.cpu_caches[cpu]
        if c["page"] is None:
            return {"status": "NOOP"}

        slab = c["page"]
        slab.freelist.extend(c["freelist"])
        c["freelist"] = []
        slab.frozen = False
        slab.cpu_owner = None
        c["page"] = None

        if slab.inuse == 0:
            self.buddy_free_count += 1
            for o in slab.all_objects:
                del self.object_map[o]
            return {"status": "UNFROZEN_AND_FREED", "slab": slab.page_id}
        elif slab.inuse < self.objects_per_slab:
            if len(c["partial"]) < self.cpu_partial_limit:
                c["partial"].append(slab)
                return {"status": "UNFROZEN_TO_CPU_PARTIAL", "slab": slab.page_id}
            else:
                self.node_lock_acquisitions += 1
                self.node_partial.append(slab)
                return {"status": "UNFROZEN_TO_NODE_PARTIAL", "slab": slab.page_id}
        return {"status": "UNFROZEN_FULL", "slab": slab.page_id}

    def get_metrics(self):
        live_slabs_set = set(self.object_map.values())
        live_objects = sum(s.inuse for s in live_slabs_set)
        live_slabs = len(live_slabs_set)
        total_capacity = live_slabs * self.objects_per_slab
        efficiency = round((live_objects / total_capacity * 100.0), 2) if total_capacity > 0 else 100.0

        cpu_states = {}
        for cpu, c in self.cpu_caches.items():
            cpu_states[str(cpu)] = {
                "active_slab": c["page"].page_id if c["page"] else None,
                "local_free_count": len(c["freelist"]),
                "cpu_partial_slabs": [s.page_id for s in c["partial"]]
            }

        return {
            "alloc_paths": self.alloc_paths,
            "free_paths": self.free_paths,
            "node_lock_acquisitions": self.node_lock_acquisitions,
            "live_objects_inuse": live_objects,
            "live_slabs_count": live_slabs,
            "total_buddy_slabs_allocated": self.buddy_alloc_count,
            "total_buddy_slabs_freed": self.buddy_free_count,
            "node_partial_slabs": [s.page_id for s in self.node_partial],
            "cpu_caches": cpu_states,
            "memory_efficiency_pct": efficiency
        }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    data = json.loads(raw)
    config = data.get("config", {})
    allocator = SlubAllocator(config)
    ops = data.get("operations", [])
    history = []

    for op in ops:
        op_type = op.get("op")
        cpu = op.get("cpu", 0)
        if op_type == "ALLOC":
            res = allocator.alloc(cpu)
            history.append(res)
        elif op_type == "FREE":
            res = allocator.free(cpu, op.get("obj_id"))
            history.append(res)
        elif op_type == "UNFREEZE":
            res = allocator.unfreeze_cpu_slab(cpu)
            history.append(res)

    metrics = allocator.get_metrics()
    output = {
        "operations_processed": len(ops),
        "history": history,
        "metrics": metrics
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
