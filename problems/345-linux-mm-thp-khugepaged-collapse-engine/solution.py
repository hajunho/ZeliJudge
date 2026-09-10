import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_SIZE_4K = 4096
HUGE_PAGE_SIZE_2M = 2097152
PTE_COUNT_PER_PMD = 512

class PMDEntry:
    def __init__(self, pmd_index):
        self.pmd_index = pmd_index
        self.is_huge = False
        self.huge_pfn = None
        self.ptes = [None] * PTE_COUNT_PER_PMD

class THPEngine:
    def __init__(self, config):
        self.thp_mode = config.get("thp_mode", "always")
        self.max_ptes_none = config.get("max_ptes_none", 64)
        self.next_pfn = 1000
        self.pmds = {}
        self.stats = {
            "thp_fault_alloc": 0,
            "thp_fault_fallback": 0,
            "thp_collapse_alloc": 0,
            "thp_split_count": 0
        }

    def _get_pmd(self, vaddr):
        pmd_idx = vaddr // HUGE_PAGE_SIZE_2M
        if pmd_idx not in self.pmds:
            self.pmds[pmd_idx] = PMDEntry(pmd_idx)
        return self.pmds[pmd_idx]

    def page_fault(self, op):
        vaddr = op["vaddr"]
        madv_huge = op.get("madv_huge", False)
        fragmented = op.get("memory_fragmented", False)

        pmd = self._get_pmd(vaddr)
        offset_in_pmd = (vaddr % HUGE_PAGE_SIZE_2M) // PAGE_SIZE_4K

        if pmd.is_huge:
            return {"status": "ALREADY_MAPPED_HUGE", "vaddr": vaddr, "pmd_index": pmd.pmd_index}

        can_thp = False
        if self.thp_mode == "always":
            can_thp = True
        elif self.thp_mode == "madvise" and madv_huge:
            can_thp = True

        if can_thp and not fragmented:
            empty = all(p is None for p in pmd.ptes)
            if empty:
                pmd.is_huge = True
                pmd.huge_pfn = self.next_pfn
                self.next_pfn += PTE_COUNT_PER_PMD
                self.stats["thp_fault_alloc"] += 1
                return {
                    "status": "THP_FAULT_ALLOC_SUCCESS",
                    "vaddr": vaddr,
                    "pmd_index": pmd.pmd_index,
                    "huge_pfn": pmd.huge_pfn
                }

        if pmd.ptes[offset_in_pmd] is None:
            pmd.ptes[offset_in_pmd] = self.next_pfn
            self.next_pfn += 1
            self.stats["thp_fault_fallback"] += 1
            return {
                "status": "PTE_4K_ALLOC_SUCCESS",
                "vaddr": vaddr,
                "pmd_index": pmd.pmd_index,
                "pte_index": offset_in_pmd,
                "pfn": pmd.ptes[offset_in_pmd]
            }
        else:
            return {
                "status": "ALREADY_MAPPED_4K",
                "vaddr": vaddr,
                "pmd_index": pmd.pmd_index,
                "pte_index": offset_in_pmd
            }

    def khugepaged_collapse(self, op):
        pmd_idx = op["pmd_index"]
        if pmd_idx not in self.pmds:
            return {"status": "PMD_NOT_FOUND", "pmd_index": pmd_idx}

        pmd = self.pmds[pmd_idx]
        if pmd.is_huge:
            return {"status": "ALREADY_HUGE", "pmd_index": pmd_idx}

        none_count = sum(1 for p in pmd.ptes if p is None)
        present_count = PTE_COUNT_PER_PMD - none_count

        if none_count > self.max_ptes_none:
            return {
                "status": "COLLAPSE_SKIPPED_TOO_SPARSE",
                "pmd_index": pmd_idx,
                "present_ptes": present_count,
                "required_min": PTE_COUNT_PER_PMD - self.max_ptes_none
            }

        pmd.is_huge = True
        pmd.huge_pfn = self.next_pfn
        self.next_pfn += PTE_COUNT_PER_PMD
        pmd.ptes = [None] * PTE_COUNT_PER_PMD
        self.stats["thp_collapse_alloc"] += 1

        return {
            "status": "COLLAPSE_SUCCESS",
            "pmd_index": pmd_idx,
            "huge_pfn": pmd.huge_pfn,
            "collapsed_4k_pages": present_count
        }

    def split_huge_page(self, op):
        pmd_idx = op["pmd_index"]
        if pmd_idx not in self.pmds:
            return {"status": "PMD_NOT_FOUND", "pmd_index": pmd_idx}

        pmd = self.pmds[pmd_idx]
        if not pmd.is_huge:
            return {"status": "NOT_HUGE", "pmd_index": pmd_idx}

        base_pfn = pmd.huge_pfn
        pmd.is_huge = False
        pmd.huge_pfn = None
        for i in range(PTE_COUNT_PER_PMD):
            pmd.ptes[i] = base_pfn + i

        self.stats["thp_split_count"] += 1
        return {
            "status": "SPLIT_SUCCESS",
            "pmd_index": pmd_idx,
            "restored_ptes": PTE_COUNT_PER_PMD
        }

    def get_pmd_status(self, op):
        pmd_idx = op["pmd_index"]
        if pmd_idx not in self.pmds:
            return None
        pmd = self.pmds[pmd_idx]
        present = sum(1 for p in pmd.ptes if p is not None)
        return {
            "pmd_index": pmd.pmd_index,
            "is_huge": pmd.is_huge,
            "huge_pfn": pmd.huge_pfn,
            "present_4k_ptes": present if not pmd.is_huge else 512
        }

    def get_stats(self):
        return {
            "thp_mode": self.thp_mode,
            "total_pmds": len(self.pmds),
            "huge_pmds_count": sum(1 for p in self.pmds.values() if p.is_huge),
            "stats": self.stats
        }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = THPEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "PAGE_FAULT":
            results.append(engine.page_fault(op))
        elif name == "COLLAPSE":
            results.append(engine.khugepaged_collapse(op))
        elif name == "SPLIT":
            results.append(engine.split_huge_page(op))
        elif name == "GET_PMD_STATUS":
            results.append(engine.get_pmd_status(op))
        elif name == "GET_STATS":
            results.append(engine.get_stats())
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
