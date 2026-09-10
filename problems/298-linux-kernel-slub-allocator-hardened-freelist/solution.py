# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class SLUBKernelAllocator:
    def __init__(self, config=None):
        config = config or {}
        self.obj_size = config.get("obj_size", 64)
        self.align = config.get("align", 8)
        self.slab_size = config.get("slab_size", 4096)
        self.hardened = config.get("hardened", True)
        self.random_cookie = config.get("cookie", 0x5A5A5A5A12345678)
        self.min_partial = config.get("min_partial", 2)

        # Compute aligned object size
        self.actual_size = ((self.obj_size + self.align - 1) // self.align) * self.align
        self.objs_per_slab = self.slab_size // self.actual_size

        self.next_slab_addr = 0x100000  # 1MB base
        self.slabs = {}                 # slab_id -> slab_dict
        self.cpu_slab = None            # Active kmem_cache_cpu slab_id
        self.node_partial = []          # List of slab_ids in partial list
        self.active_objects = {}        # obj_id -> addr
        self.addr_to_meta = {}          # addr -> {"slab_id": id, "obj_id": id}

        self.stats = {
            "slabs_allocated": 0,
            "slabs_freed": 0,
            "fast_path_allocs": 0,
            "slow_path_allocs": 0,
            "fast_path_frees": 0,
            "slow_path_frees": 0,
            "double_frees_detected": 0,
            "corruptions_detected": 0
        }
        self.events = []

    def _encode(self, next_ptr, ptr_addr):
        if not self.hardened:
            return next_ptr or 0
        val = next_ptr if next_ptr is not None else 0
        return val ^ ptr_addr ^ self.random_cookie

    def _decode(self, encoded_val, ptr_addr):
        if not self.hardened:
            return None if encoded_val == 0 else encoded_val
        val = encoded_val ^ ptr_addr ^ self.random_cookie
        return None if val == 0 else val

    def _new_slab(self):
        slab_id = self.stats["slabs_allocated"]
        self.stats["slabs_allocated"] += 1
        base = self.next_slab_addr
        self.next_slab_addr += self.slab_size

        slab = {
            "id": slab_id,
            "base": base,
            "inuse": 0,
            "freelist_head": base,
            "memory": {},
            "freelist_set": set()
        }

        # Build initial freelist
        for i in range(self.objs_per_slab):
            curr_addr = base + i * self.actual_size
            next_addr = (base + (i + 1) * self.actual_size) if i + 1 < self.objs_per_slab else None
            slab["memory"][curr_addr] = self._encode(next_addr, curr_addr)
            slab["freelist_set"].add(curr_addr)

        self.slabs[slab_id] = slab
        return slab

    def alloc(self, obj_id):
        # Check if CPU slab has free objects (Fast path)
        if self.cpu_slab is not None:
            slab = self.slabs[self.cpu_slab]
            if slab["freelist_head"] is not None:
                self.stats["fast_path_allocs"] += 1
                addr = slab["freelist_head"]

                # Validate freelist pointer integrity
                encoded_next = slab["memory"].get(addr, 0)
                decoded_next = self._decode(encoded_next, addr)

                # Integrity check: decoded_next must be None or valid slab object
                if decoded_next is not None:
                    is_valid_addr = (
                        decoded_next >= slab["base"] and
                        decoded_next < slab["base"] + self.slab_size and
                        (decoded_next - slab["base"]) % self.actual_size == 0
                    )
                    if not is_valid_addr:
                        self.stats["corruptions_detected"] += 1
                        evt = {"op": "ALLOC", "id": obj_id, "error": "FREELIST_CORRUPTION_DETECTED", "addr": addr}
                        self.events.append(evt)
                        return evt

                slab["freelist_head"] = decoded_next
                slab["freelist_set"].discard(addr)
                slab["inuse"] += 1
                self.active_objects[obj_id] = addr
                self.addr_to_meta[addr] = {"slab_id": slab["id"], "obj_id": obj_id}

                evt = {"op": "ALLOC", "id": obj_id, "addr": addr, "path": "fast_path", "slab_id": slab["id"]}
                self.events.append(evt)
                return evt

        # Slow path: need to refill cpu_slab from node partial or new slab
        self.stats["slow_path_allocs"] += 1

        if self.node_partial:
            next_slab_id = self.node_partial.pop(0)
            self.cpu_slab = next_slab_id
        else:
            new_slab = self._new_slab()
            self.cpu_slab = new_slab["id"]

        slab = self.slabs[self.cpu_slab]
        addr = slab["freelist_head"]
        encoded_next = slab["memory"].get(addr, 0)
        decoded_next = self._decode(encoded_next, addr)

        if decoded_next is not None:
            is_valid_addr = (
                decoded_next >= slab["base"] and
                decoded_next < slab["base"] + self.slab_size and
                (decoded_next - slab["base"]) % self.actual_size == 0
            )
            if not is_valid_addr:
                self.stats["corruptions_detected"] += 1
                evt = {"op": "ALLOC", "id": obj_id, "error": "FREELIST_CORRUPTION_DETECTED", "addr": addr}
                self.events.append(evt)
                return evt

        slab["freelist_head"] = decoded_next
        slab["freelist_set"].discard(addr)
        slab["inuse"] += 1
        self.active_objects[obj_id] = addr
        self.addr_to_meta[addr] = {"slab_id": slab["id"], "obj_id": obj_id}

        evt = {"op": "ALLOC", "id": obj_id, "addr": addr, "path": "slow_path", "slab_id": slab["id"]}
        self.events.append(evt)
        return evt

    def free(self, obj_id):
        if obj_id not in self.active_objects:
            self.stats["double_frees_detected"] += 1
            evt = {"op": "FREE", "id": obj_id, "error": "DOUBLE_FREE_OR_UNALLOCATED"}
            self.events.append(evt)
            return evt

        addr = self.active_objects.pop(obj_id)
        meta = self.addr_to_meta.pop(addr)
        slab_id = meta["slab_id"]
        slab = self.slabs[slab_id]

        is_fast_path = (self.cpu_slab == slab_id)
        if is_fast_path:
            self.stats["fast_path_frees"] += 1
            path = "fast_path"
        else:
            self.stats["slow_path_frees"] += 1
            path = "slow_path"

        # Prepend to freelist
        old_head = slab["freelist_head"]
        slab["memory"][addr] = self._encode(old_head, addr)
        slab["freelist_head"] = addr
        slab["freelist_set"].add(addr)
        slab["inuse"] -= 1

        # Check slab reclamation if inuse == 0
        if slab["inuse"] == 0:
            if not is_fast_path and len(self.node_partial) >= self.min_partial:
                if slab_id in self.node_partial:
                    self.node_partial.remove(slab_id)
                del self.slabs[slab_id]
                self.stats["slabs_freed"] += 1
                evt = {"op": "FREE", "id": obj_id, "addr": addr, "path": path, "slab_id": slab_id, "slab_reclaimed": True}
                self.events.append(evt)
                return evt
        elif not is_fast_path and slab_id not in self.node_partial:
            self.node_partial.append(slab_id)

        evt = {"op": "FREE", "id": obj_id, "addr": addr, "path": path, "slab_id": slab_id, "slab_reclaimed": False}
        self.events.append(evt)
        return evt

    def corrupt(self, addr, bogus_encoded):
        for s in self.slabs.values():
            if addr in s["memory"]:
                s["memory"][addr] = bogus_encoded
                evt = {"op": "CORRUPT", "addr": addr, "status": "INJECTED"}
                self.events.append(evt)
                return evt
        evt = {"op": "CORRUPT", "addr": addr, "status": "ADDR_NOT_FOUND"}
        self.events.append(evt)
        return evt

    def execute_ops(self, operations):
        for op in operations:
            otype = op.get("op")
            if otype == "ALLOC":
                self.alloc(op.get("id"))
            elif otype == "FREE":
                self.free(op.get("id"))
            elif otype == "CORRUPT":
                self.corrupt(op.get("addr"), op.get("bogus_encoded"))

        active_slab = self.slabs.get(self.cpu_slab)
        return {
            "events": self.events,
            "stats": self.stats,
            "final_state": {
                "active_slab_id": self.cpu_slab,
                "active_slab_inuse": active_slab["inuse"] if active_slab else 0,
                "partial_slabs_count": len(self.node_partial),
                "total_live_slabs": len(self.slabs)
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    operations = data.get("operations", [])
    allocator = SLUBKernelAllocator(config)
    res = allocator.execute_ops(operations)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
