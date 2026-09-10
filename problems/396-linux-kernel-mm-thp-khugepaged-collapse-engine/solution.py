# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #396 Solution:
Linux Kernel Memory Management: Transparent Hugepage (THP) khugepaged Collapse Engine
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_SIZE = 4096
HPAGE_SIZE = 2 * 1024 * 1024
PAGES_PER_HPAGE = 512

class PMDWindow:
    def __init__(self, pmd_idx):
        self.pmd_idx = int(pmd_idx)
        self.start_addr = self.pmd_idx * HPAGE_SIZE
        self.end_addr = self.start_addr + HPAGE_SIZE
        self.status = "SPLIT_4K"
        self.pages = [{"state": "NONE", "referenced": False} for _ in range(PAGES_PER_HPAGE)]

    def count_states(self):
        counts = {"NONE": 0, "PRESENT": 0, "SWAPPED": 0, "SHARED": 0, "REFERENCED": 0}
        for p in self.pages:
            st = p["state"]
            counts[st] = counts.get(st, 0) + 1
            if p["referenced"]:
                counts["REFERENCED"] += 1
        return counts

    def to_dict(self):
        return {
            "pmd_idx": self.pmd_idx,
            "start_addr": f"0x{self.start_addr:08x}",
            "end_addr": f"0x{self.end_addr:08x}",
            "status": self.status,
            "page_counts": self.count_states()
        }

class KhugepagedEngine:
    def __init__(self, config):
        self.max_ptes_none = int(config.get("max_ptes_none", 64))
        self.max_ptes_swap = int(config.get("max_ptes_swap", 16))
        self.max_ptes_shared = int(config.get("max_ptes_shared", 0))
        self.min_referenced = int(config.get("min_referenced", 32))
        self.scan_rate_pmds_per_tick = int(config.get("scan_rate_pmds_per_tick", 2))
        self.cursor_pmd_idx = 0

        self.pmd_windows = {}
        self.total_scans = 0
        self.successful_collapses = 0
        self.failed_collapses = 0
        self.failure_reasons = {}
        self.collapse_log = []
        self.freed_pte_table_bytes = 0

    def get_or_create_pmd(self, pmd_idx):
        if pmd_idx not in self.pmd_windows:
            self.pmd_windows[pmd_idx] = PMDWindow(pmd_idx)
        return self.pmd_windows[pmd_idx]

    def set_page(self, pmd_idx, page_idx, state, referenced=False):
        pmd = self.get_or_create_pmd(pmd_idx)
        if 0 <= page_idx < PAGES_PER_HPAGE:
            pmd.pages[page_idx] = {"state": state, "referenced": bool(referenced)}

    def scan_and_collapse_pmd(self, pmd_idx):
        if pmd_idx not in self.pmd_windows:
            return {"status": "SKIP", "reason": "UNMAPPED_PMD"}

        pmd = self.pmd_windows[pmd_idx]
        self.total_scans += 1

        if pmd.status == "COLLAPSED_2MB":
            return {"status": "SKIP", "reason": "ALREADY_COLLAPSED"}

        counts = pmd.count_states()

        if counts["NONE"] > self.max_ptes_none:
            reason = f"SCAN_FAIL_TOO_MANY_NONE (none={counts['NONE']} > max={self.max_ptes_none})"
            self.failed_collapses += 1
            self.failure_reasons[reason] = self.failure_reasons.get(reason, 0) + 1
            return {"status": "FAIL", "reason": reason, "counts": counts}

        if counts["SWAPPED"] > self.max_ptes_swap:
            reason = f"SCAN_FAIL_TOO_MANY_SWAP (swap={counts['SWAPPED']} > max={self.max_ptes_swap})"
            self.failed_collapses += 1
            self.failure_reasons[reason] = self.failure_reasons.get(reason, 0) + 1
            return {"status": "FAIL", "reason": reason, "counts": counts}

        if counts["SHARED"] > self.max_ptes_shared:
            reason = f"SCAN_FAIL_SHARED_PAGE (shared={counts['SHARED']} > max={self.max_ptes_shared})"
            self.failed_collapses += 1
            self.failure_reasons[reason] = self.failure_reasons.get(reason, 0) + 1
            return {"status": "FAIL", "reason": reason, "counts": counts}

        if counts["REFERENCED"] < self.min_referenced:
            reason = f"SCAN_FAIL_COLD_PAGES (referenced={counts['REFERENCED']} < min={self.min_referenced})"
            self.failed_collapses += 1
            self.failure_reasons[reason] = self.failure_reasons.get(reason, 0) + 1
            return {"status": "FAIL", "reason": reason, "counts": counts}

        pmd.status = "COLLAPSED_2MB"
        self.successful_collapses += 1
        self.freed_pte_table_bytes += PAGE_SIZE

        collapse_record = {
            "pmd_idx": pmd_idx,
            "start_addr": f"0x{pmd.start_addr:08x}",
            "end_addr": f"0x{pmd.end_addr:08x}",
            "pages_collapsed": PAGES_PER_HPAGE,
            "swapped_in": counts["SWAPPED"],
            "zero_filled": counts["NONE"],
            "freed_pte_table_bytes": PAGE_SIZE
        }
        self.collapse_log.append(collapse_record)
        return {"status": "SUCCESS", "details": collapse_record}

    def run_simulation(self, initial_pages, scan_epochs=1):
        for p_info in initial_pages:
            pmd_idx = int(p_info["pmd_idx"])
            page_idx = int(p_info["page_idx"])
            state = p_info.get("state", "PRESENT")
            ref = p_info.get("referenced", False)
            self.set_page(pmd_idx, page_idx, state, ref)

        all_pmd_indices = sorted(self.pmd_windows.keys())
        if not all_pmd_indices:
            return self.get_summary()

        for epoch in range(scan_epochs):
            for _ in range(self.scan_rate_pmds_per_tick):
                if not all_pmd_indices:
                    break
                target_pmd = all_pmd_indices[self.cursor_pmd_idx % len(all_pmd_indices)]
                self.cursor_pmd_idx += 1
                self.scan_and_collapse_pmd(target_pmd)

        return self.get_summary()

    def get_summary(self):
        pmd_states = {str(k): self.pmd_windows[k].to_dict() for k in sorted(self.pmd_windows.keys())}
        return {
            "total_scans": self.total_scans,
            "successful_collapses": self.successful_collapses,
            "failed_collapses": self.failed_collapses,
            "failure_reasons": self.failure_reasons,
            "freed_pte_table_bytes": self.freed_pte_table_bytes,
            "collapse_log": self.collapse_log,
            "pmd_states": pmd_states
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    initial_pages = data.get("initial_pages", [])
    scan_epochs = data.get("scan_epochs", 1)
    engine = KhugepagedEngine(config)
    res = engine.run_simulation(initial_pages, scan_epochs)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
