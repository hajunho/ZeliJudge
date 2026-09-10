# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #400 Solution:
Linux Kernel Memory Management: Maple Tree (RCU-Safe B-Tree VMA Allocator) Engine
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class VMA:
    def __init__(self, vm_start, vm_end, vm_flags, name=""):
        self.vm_start = int(vm_start)
        self.vm_end = int(vm_end)
        self.vm_flags = vm_flags
        self.name = name

    @property
    def size(self):
        return self.vm_end - self.vm_start

    def to_dict(self):
        return {
            "start": f"0x{self.vm_start:08x}",
            "end": f"0x{self.vm_end:08x}",
            "size_bytes": self.size,
            "flags": self.vm_flags,
            "name": self.name
        }

class MapleTree:
    def __init__(self, max_slots=4):
        self.max_slots = max_slots
        self.vmas = []
        self.node_splits = 0
        self.node_merges = 0
        self.rcu_reads = 0

    def insert_vma(self, vm_start, vm_end, vm_flags, name=""):
        for v in self.vmas:
            if not (vm_end <= v.vm_start or vm_start >= v.vm_end):
                return {"status": "ERROR_OVERLAP", "conflict": v.to_dict()}

        new_vma = VMA(vm_start, vm_end, vm_flags, name)
        self.vmas.append(new_vma)
        self.vmas.sort(key=lambda x: x.vm_start)

        if len(self.vmas) > self.max_slots and len(self.vmas) % (self.max_slots // 2 + 1) == 0:
            self.node_splits += 1

        return {"status": "SUCCESS", "vma": new_vma.to_dict()}

    def erase_range(self, start, end):
        to_keep = []
        erased_count = 0
        for v in self.vmas:
            if v.vm_end <= start or v.vm_start >= end:
                to_keep.append(v)
            elif v.vm_start >= start and v.vm_end <= end:
                erased_count += 1
            elif v.vm_start < start and v.vm_end > end:
                part1 = VMA(v.vm_start, start, v.vm_flags, v.name)
                part2 = VMA(end, v.vm_end, v.vm_flags, v.name)
                to_keep.append(part1)
                to_keep.append(part2)
                erased_count += 1
            elif v.vm_start < start:
                part = VMA(v.vm_start, start, v.vm_flags, v.name)
                to_keep.append(part)
                erased_count += 1
            else:
                part = VMA(end, v.vm_end, v.vm_flags, v.name)
                to_keep.append(part)
                erased_count += 1

        self.vmas = sorted(to_keep, key=lambda x: x.vm_start)
        if erased_count > 0:
            self.node_merges += 1

        return {"status": "SUCCESS", "erased_count": erased_count}

    def mas_walk(self, addr):
        self.rcu_reads += 1
        for v in self.vmas:
            if v.vm_start <= addr < v.vm_end:
                return {"status": "FOUND", "vma": v.to_dict()}
        return {"status": "NOT_FOUND"}

    def mas_find_gap(self, size, min_addr=0x10000, max_addr=0x80000000):
        cur = min_addr
        for v in self.vmas:
            if v.vm_start > cur:
                gap = v.vm_start - cur
                if gap >= size:
                    return {"status": "GAP_FOUND", "gap_start": f"0x{cur:08x}", "gap_size": gap}
            cur = max(cur, v.vm_end)

        if max_addr - cur >= size:
            return {"status": "GAP_FOUND", "gap_start": f"0x{cur:08x}", "gap_size": max_addr - cur}

        return {"status": "NO_GAP_FOUND"}

    def run_simulation(self, operations):
        results = []
        for op in operations:
            act = op["action"]
            if act == "MMAP":
                res = self.insert_vma(op["start"], op["end"], op.get("flags", "rw-p"), op.get("name", ""))
                results.append({"op": act, **res})
            elif act == "MUNMAP":
                res = self.erase_range(op["start"], op["end"])
                results.append({"op": act, **res})
            elif act == "MAS_WALK":
                res = self.mas_walk(op["addr"])
                results.append({"op": act, "query_addr": f"0x{op['addr']:08x}", **res})
            elif act == "FIND_GAP":
                res = self.mas_find_gap(op["size"], op.get("min_addr", 0x10000), op.get("max_addr", 0x80000000))
                results.append({"op": act, "size_requested": op["size"], **res})

        return {
            "total_vmas": len(self.vmas),
            "node_splits": self.node_splits,
            "node_merges": self.node_merges,
            "rcu_reads": self.rcu_reads,
            "vmas": [v.to_dict() for v in self.vmas],
            "operation_results": results
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    max_slots = data.get("max_slots", 4)
    operations = data.get("operations", [])
    mt = MapleTree(max_slots)
    res = mt.run_simulation(operations)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
