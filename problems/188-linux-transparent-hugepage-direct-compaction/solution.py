import sys
import json
import math
from typing import Dict, List, Any

class LinuxTransparentHugePagesSimulator:
    def __init__(self, data: Dict[str, Any]):
        cfg = data.get("system", {})
        self.mode: str = cfg.get("thp_mode", "THP_ALWAYS")
        # Supported: "THP_ALWAYS", "THP_MADVISE", "THP_NEVER"
        self.defrag_mode: str = cfg.get("thp_defrag_mode", "SYNC_DIRECT_COMPACT")
        # Supported: "SYNC_DIRECT_COMPACT", "ASYNC_KHUGEPAGED", "NEVER"
        self.base_page_size_kb: int = int(cfg.get("base_page_size_kb", 4))
        self.huge_page_size_kb: int = int(cfg.get("huge_page_size_kb", 2048))
        self.std_alloc_latency_us: float = float(cfg.get("standard_alloc_latency_us", 2.0))
        self.direct_compaction_latency_us: float = float(cfg.get("direct_compaction_latency_us", 15000.0))
        self.cow_copy_per_kb_us: float = float(cfg.get("cow_copy_per_kb_us", 0.5))
        self.tlb_miss_penalty_us: float = float(cfg.get("tlb_miss_penalty_per_req_us", 5.0))

        self.memory_fragmentation: float = float(cfg.get("initial_fragmentation", 0.0))  # 0.0 to 1.0
        self.allocations: Dict[str, Dict[str, Any]] = {}

        # Metrics
        self.total_allocations: int = 0
        self.huge_pages_allocated: int = 0
        self.base_pages_allocated: int = 0
        self.direct_compaction_stalls: int = 0
        self.total_stall_time_us: float = 0.0
        self.total_latency_us: float = 0.0
        self.total_memory_allocated_kb: int = 0
        self.cow_copied_memory_kb: int = 0
        self.cow_amplified_memory_kb: int = 0
        self.event_timeline: List[Dict[str, Any]] = []

    def allocate(self, alloc_id: str, size_kb: int, is_madvised: bool, t: float):
        self.total_allocations += 1
        use_thp = False

        if self.mode == "THP_ALWAYS":
            use_thp = True
        elif self.mode == "THP_MADVISE":
            use_thp = is_madvised
        elif self.mode == "THP_NEVER":
            use_thp = False

        latency = self.std_alloc_latency_us
        stalled = False
        stall_time = 0.0

        if use_thp and size_kb >= self.base_page_size_kb:
            hp_count = max(1, math.ceil(size_kb / self.huge_page_size_kb))
            # If memory is fragmented and defrag is synchronous direct compaction
            if self.memory_fragmentation >= 0.5 and self.defrag_mode == "SYNC_DIRECT_COMPACT":
                stalled = True
                stall_time = self.direct_compaction_latency_us * hp_count
                self.direct_compaction_stalls += hp_count
                self.total_stall_time_us += stall_time
                latency += stall_time

            allocated_kb = hp_count * self.huge_page_size_kb
            self.huge_pages_allocated += hp_count
            self.total_memory_allocated_kb += allocated_kb
            self.allocations[alloc_id] = {
                "page_type": "HUGE_PAGE_2MB",
                "requested_kb": size_kb,
                "allocated_kb": allocated_kb,
                "pages_count": hp_count
            }
        else:
            bp_count = math.ceil(size_kb / self.base_page_size_kb)
            allocated_kb = bp_count * self.base_page_size_kb
            self.base_pages_allocated += bp_count
            self.total_memory_allocated_kb += allocated_kb
            self.allocations[alloc_id] = {
                "page_type": "BASE_PAGE_4KB",
                "requested_kb": size_kb,
                "allocated_kb": allocated_kb,
                "pages_count": bp_count
            }

        self.total_latency_us += latency
        self.event_timeline.append({
            "wallclock_ms": t,
            "op": "ALLOC",
            "alloc_id": alloc_id,
            "size_kb": size_kb,
            "page_type": self.allocations[alloc_id]["page_type"],
            "stalled": stalled,
            "latency_us": round(latency, 2)
        })

    def cow_write(self, alloc_id: str, bytes_modified: int, t: float):
        alloc = self.allocations.get(alloc_id)
        if not alloc:
            return

        is_hp = (alloc["page_type"] == "HUGE_PAGE_2MB")
        if is_hp:
            # Entire 2MB page copied!
            copied_kb = self.huge_page_size_kb
            ideal_kb = self.base_page_size_kb
            amplified_kb = copied_kb - ideal_kb
        else:
            # Only 4KB copied
            copied_kb = self.base_page_size_kb
            amplified_kb = 0

        self.cow_copied_memory_kb += copied_kb
        self.cow_amplified_memory_kb += amplified_kb

        latency = copied_kb * self.cow_copy_per_kb_us
        self.total_latency_us += latency

        self.event_timeline.append({
            "wallclock_ms": t,
            "op": "COW_WRITE",
            "alloc_id": alloc_id,
            "bytes_modified": bytes_modified,
            "page_type": alloc["page_type"],
            "copied_kb": copied_kb,
            "amplified_kb": amplified_kb,
            "latency_us": round(latency, 2)
        })

    def read_scan(self, alloc_id: str, pages_to_scan: int, t: float):
        alloc = self.allocations.get(alloc_id)
        if not alloc:
            return

        is_hp = (alloc["page_type"] == "HUGE_PAGE_2MB")
        # If standard 4KB pages and scanning > 64 pages, TLB misses incur penalty
        if not is_hp and pages_to_scan > 64:
            tlb_penalty = (pages_to_scan / 64) * self.tlb_miss_penalty_us
        else:
            tlb_penalty = 0.0

        latency = 1.0 + tlb_penalty
        self.total_latency_us += latency

        self.event_timeline.append({
            "wallclock_ms": t,
            "op": "READ_SCAN",
            "alloc_id": alloc_id,
            "pages_scanned": pages_to_scan,
            "tlb_penalty_us": round(tlb_penalty, 2),
            "latency_us": round(latency, 2)
        })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            t = float(item.get("wallclock_ms", 0.0))
            op = item.get("op")
            if op == "SET_FRAGMENTATION":
                self.memory_fragmentation = float(item["fragmentation"])
            elif op == "ALLOC":
                self.allocate(item["alloc_id"], int(item["size_kb"]), bool(item.get("is_madvised", False)), t)
            elif op == "COW_WRITE":
                self.cow_write(item["alloc_id"], int(item.get("bytes_modified", 64)), t)
            elif op == "READ_SCAN":
                self.read_scan(item["alloc_id"], int(item.get("pages_to_scan", 100)), t)

        total_ops = len(self.event_timeline)
        avg_latency = round(self.total_latency_us / total_ops, 2) if total_ops > 0 else 0.0

        if self.mode == "THP_ALWAYS" and self.direct_compaction_stalls > 0:
            verdict = "SYNCHRONOUS_DIRECT_COMPACTION_LATENCY_SPIKE"
        elif self.mode == "THP_ALWAYS" and self.cow_amplified_memory_kb > 0:
            verdict = "COW_MEMORY_AMPLIFICATION_EXPLOSION"
        elif self.mode == "THP_MADVISE":
            verdict = "OPTIMAL_MADVISE_SELECTIVE_HUGEPAGE"
        else:
            verdict = "STABLE_4KB_PAGES_NO_STALLS"

        # Success criteria: if direct compaction stall occurred or severe CoW amplification occurred, FAILED
        status = "FAILED" if (self.direct_compaction_stalls > 0 or self.cow_amplified_memory_kb >= 4096) else "SUCCESS"

        return {
            "status": status,
            "summary": {
                "thp_mode": self.mode,
                "defrag_mode": self.defrag_mode,
                "total_allocations": self.total_allocations,
                "huge_pages_allocated": self.huge_pages_allocated,
                "base_pages_allocated": self.base_pages_allocated,
                "direct_compaction_stalls": self.direct_compaction_stalls,
                "total_stall_time_us": round(self.total_stall_time_us, 2)
            },
            "metrics": {
                "total_allocations": self.total_allocations,
                "huge_pages_allocated": self.huge_pages_allocated,
                "base_pages_allocated": self.base_pages_allocated,
                "total_memory_allocated_kb": self.total_memory_allocated_kb,
                "direct_compaction_stalls": self.direct_compaction_stalls,
                "total_stall_time_us": round(self.total_stall_time_us, 2),
                "cow_copied_memory_kb": self.cow_copied_memory_kb,
                "cow_amplified_memory_kb": self.cow_amplified_memory_kb,
                "average_latency_us": avg_latency,
                "verdict": verdict
            },
            "sample_events": self.event_timeline[:15]
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    input_data = json.loads(raw_data)
    simulator = LinuxTransparentHugePagesSimulator(input_data)
    workload = input_data.get("workload", [])
    output = simulator.run(workload)
    print(json.dumps(output, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    solve()
