# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #401 Solution:
Linux Kernel Virtualization: KVM Dirty Ring Buffer Live Migration & Scalability Engine
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class KVMDirtyRing:
    def __init__(self, vcpu_id, ring_size=4):
        self.vcpu_id = int(vcpu_id)
        self.ring_size = int(ring_size)
        self.head = 0
        self.tail = 0
        self.entries = [{"gfn": None, "flags": "EMPTY"} for _ in range(self.ring_size)]
        self.is_full = False

    @property
    def count(self):
        return self.tail - self.head

    def push_dirty_gfn(self, gfn):
        if self.count >= self.ring_size:
            self.is_full = True
            return False

        idx = self.tail % self.ring_size
        self.entries[idx] = {"gfn": int(gfn), "flags": "DIRTY"}
        self.tail += 1
        if self.count >= self.ring_size:
            self.is_full = True
        return True

    def reap_dirty_gfns(self):
        reaped = []
        cur = self.head
        while cur < self.tail:
            idx = cur % self.ring_size
            if self.entries[idx]["flags"] == "DIRTY":
                reaped.append(self.entries[idx]["gfn"])
                self.entries[idx]["flags"] = "RESET"
            cur += 1
        return reaped

    def reset_ring(self):
        while self.head < self.tail:
            idx = self.head % self.ring_size
            if self.entries[idx]["flags"] == "RESET":
                self.entries[idx]["flags"] = "EMPTY"
                self.entries[idx]["gfn"] = None
                self.head += 1
            else:
                break
        self.is_full = (self.count >= self.ring_size)
        return self.count

    def to_dict(self):
        return {
            "vcpu_id": self.vcpu_id,
            "head": self.head,
            "tail": self.tail,
            "count": self.count,
            "is_full": self.is_full,
            "entries": self.entries
        }

class KVMDirtyRingEngine:
    def __init__(self, config):
        self.num_vcpus = int(config.get("num_vcpus", 2))
        self.ring_size = int(config.get("ring_size", 4))
        self.rings = {v: KVMDirtyRing(v, self.ring_size) for v in range(self.num_vcpus)}

        self.current_tick = 0
        self.migrated_gfns_total = []
        self.stats = {
            "total_page_writes": 0,
            "ring_full_exits": 0,
            "reaped_dirty_pages": 0,
            "reset_operations": 0,
            "throttled_write_attempts": 0
        }

    def vcpu_write_page(self, vcpu_id, gfn):
        self.current_tick += 1
        self.stats["total_page_writes"] += 1
        if vcpu_id not in self.rings:
            return {"status": "ERROR_INVALID_VCPU"}

        ring = self.rings[vcpu_id]
        if ring.is_full:
            self.stats["throttled_write_attempts"] += 1
            return {"status": "KVM_EXIT_DIRTY_RING_FULL", "vcpu_id": vcpu_id}

        success = ring.push_dirty_gfn(gfn)
        if not success or ring.is_full:
            self.stats["ring_full_exits"] += 1
            return {"status": "KVM_EXIT_DIRTY_RING_FULL", "vcpu_id": vcpu_id, "pushed": success}

        return {"status": "PUSH_SUCCESS", "vcpu_id": vcpu_id, "gfn": gfn}

    def reap_and_migrate(self, vcpu_id=None):
        self.current_tick += 1
        vcpus_to_reap = [vcpu_id] if vcpu_id is not None else sorted(self.rings.keys())
        reaped_map = {}

        for v in vcpus_to_reap:
            ring = self.rings[v]
            reaped = ring.reap_dirty_gfns()
            reaped_map[str(v)] = reaped
            self.stats["reaped_dirty_pages"] += len(reaped)
            self.migrated_gfns_total.extend(reaped)

        return reaped_map

    def reset_rings(self, vcpu_id=None):
        self.current_tick += 1
        self.stats["reset_operations"] += 1
        vcpus_to_reset = [vcpu_id] if vcpu_id is not None else sorted(self.rings.keys())
        reset_counts = {}

        for v in vcpus_to_reset:
            ring = self.rings[v]
            rem = ring.reset_ring()
            reset_counts[str(v)] = rem

        return reset_counts

    def run_simulation(self, operations):
        results = []
        for op in operations:
            act = op["action"]
            if act == "VCPU_WRITE":
                res = self.vcpu_write_page(op["vcpu_id"], op["gfn"])
                results.append({"op": act, **res})
            elif act == "REAP":
                v_target = op.get("vcpu_id", None)
                res = self.reap_and_migrate(v_target)
                results.append({"op": act, "reaped": res})
            elif act == "RESET":
                v_target = op.get("vcpu_id", None)
                res = self.reset_rings(v_target)
                results.append({"op": act, "remaining": res})

        return self.get_summary(results)

    def get_summary(self, op_results=None):
        rings_summary = {str(v): self.rings[v].to_dict() for v in sorted(self.rings.keys())}
        return {
            "total_vcpus": self.num_vcpus,
            "ring_size": self.ring_size,
            "stats": self.stats,
            "migrated_gfns_count": len(self.migrated_gfns_total),
            "migrated_gfns_total": self.migrated_gfns_total,
            "rings_state": rings_summary,
            "operation_results": op_results or []
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    operations = data.get("operations", [])
    engine = KVMDirtyRingEngine(config)
    res = engine.run_simulation(operations)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
