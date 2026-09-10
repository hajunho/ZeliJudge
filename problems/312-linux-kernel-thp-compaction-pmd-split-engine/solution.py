# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #312
Linux Kernel Transparent Huge Pages (THP) Dual-Scanner Compaction & PMD Split Engine
(mm/huge_memory.c, mm/compaction.c)

Operationalizes the Linux Kernel Virtual Memory THP Subsystem:
1. Buddy Allocator Order-K (2^K contiguous 4KB pages) natural alignment check.
2. Direct Compaction (compact_zone) dual-scanner convergence:
   - migrate_scanner: scans forward from zone start for movable allocated pages.
   - free_scanner: scans backward from zone end for unallocated target page frames.
   - Page migration: copying state/metadata and updating references until scanners meet.
3. Transparent Huge Page Compound allocation (PageHead, PageTail, pmd_mapped).
4. PMD Split (split_huge_pmd / split_huge_page) into individual regular 4KB PTEs.
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)

    config = data.get("config", {})
    total_pages = int(config.get("total_pages", 32))
    order = int(config.get("hugepage_order", 3))
    huge_len = 1 << order

    pages = []
    for i in range(total_pages):
        pages.append({
            "pfn": i,
            "state": "FREE",
            "page_type": "REGULAR_4K",
            "vma_id": None,
            "movable": True,
            "refcount": 0
        })

    for alloc in data.get("initial_allocations", []):
        for pfn in alloc.get("pfns", []):
            if 0 <= pfn < total_pages:
                pages[pfn]["state"] = "ALLOCATED"
                pages[pfn]["page_type"] = "REGULAR_4K"
                pages[pfn]["vma_id"] = alloc.get("vma_id", "vma-init")
                pages[pfn]["movable"] = bool(alloc.get("movable", True))
                pages[pfn]["refcount"] = int(alloc.get("refcount", 1))

    commands = data.get("commands", [])
    cmd_logs = []

    compaction_runs = 0
    pages_migrated_total = 0
    thp_allocated_count = 0
    pmd_splits_count = 0

    def find_aligned_free_block():
        for base in range(0, total_pages, huge_len):
            if base + huge_len <= total_pages:
                if all(pages[base + i]["state"] == "FREE" for i in range(huge_len)):
                    return base
        return -1

    def run_compaction():
        nonlocal pages_migrated_total
        mig_pfn = 0
        free_pfn = total_pages - 1
        migrated = 0

        while mig_pfn < free_pfn:
            while mig_pfn < free_pfn and not (pages[mig_pfn]["state"] == "ALLOCATED" and pages[mig_pfn]["movable"] and pages[mig_pfn]["page_type"] == "REGULAR_4K"):
                mig_pfn += 1

            while free_pfn > mig_pfn and pages[free_pfn]["state"] != "FREE":
                free_pfn -= 1

            if mig_pfn < free_pfn:
                pages[free_pfn]["state"] = "ALLOCATED"
                pages[free_pfn]["page_type"] = pages[mig_pfn]["page_type"]
                pages[free_pfn]["vma_id"] = pages[mig_pfn]["vma_id"]
                pages[free_pfn]["movable"] = pages[mig_pfn]["movable"]
                pages[free_pfn]["refcount"] = pages[mig_pfn]["refcount"]

                pages[mig_pfn]["state"] = "FREE"
                pages[mig_pfn]["page_type"] = "REGULAR_4K"
                pages[mig_pfn]["vma_id"] = None
                pages[mig_pfn]["movable"] = True
                pages[mig_pfn]["refcount"] = 0

                migrated += 1
                mig_pfn += 1
                free_pfn -= 1

                if find_aligned_free_block() != -1:
                    break

        pages_migrated_total += migrated
        return migrated

    for c_idx, cmd in enumerate(commands, start=1):
        op = cmd.get("op")
        vma_id = cmd.get("vma_id", f"vma-{c_idx}")
        log = {"command_index": c_idx, "op": op, "vma_id": vma_id, "details": {}}

        if op == "ALLOC_THP":
            base = find_aligned_free_block()
            status = "DIRECT_ALLOCATION"
            migrated_count = 0

            if base == -1:
                compaction_runs += 1
                migrated_count = run_compaction()
                base = find_aligned_free_block()
                if base != -1:
                    status = "COMPACTED_AND_ALLOCATED"
                else:
                    status = "ALLOCATION_FAILED_OUT_OF_CONTIGUITY"

            if base != -1:
                pages[base]["state"] = "ALLOCATED"
                pages[base]["page_type"] = "HUGE_2M_HEAD"
                pages[base]["vma_id"] = vma_id
                pages[base]["refcount"] = 1
                pages[base]["movable"] = False

                for offset in range(1, huge_len):
                    p = pages[base + offset]
                    p["state"] = "ALLOCATED"
                    p["page_type"] = "HUGE_2M_TAIL"
                    p["vma_id"] = vma_id
                    p["refcount"] = 0
                    p["movable"] = False

                thp_allocated_count += 1
                log["details"] = {
                    "status": status,
                    "base_pfn": base,
                    "hugepage_len": huge_len,
                    "compaction_migrated_pages": migrated_count
                }
            else:
                log["details"] = {
                    "status": status,
                    "compaction_migrated_pages": migrated_count
                }

        elif op == "SPLIT_HUGE_PMD":
            pfn = int(cmd.get("pfn", -1))
            head_pfn = -1
            if 0 <= pfn < total_pages:
                if pages[pfn]["page_type"] == "HUGE_2M_HEAD":
                    head_pfn = pfn
                elif pages[pfn]["page_type"] == "HUGE_2M_TAIL":
                    curr = pfn
                    while curr >= 0 and pages[curr]["page_type"] == "HUGE_2M_TAIL":
                        curr -= 1
                    if curr >= 0 and pages[curr]["page_type"] == "HUGE_2M_HEAD":
                        head_pfn = curr

            if head_pfn != -1:
                for offset in range(huge_len):
                    p = pages[head_pfn + offset]
                    p["page_type"] = "REGULAR_4K"
                    p["refcount"] = 1
                    p["movable"] = True

                pmd_splits_count += 1
                log["details"] = {
                    "status": "SPLIT_SUCCESS",
                    "head_pfn": head_pfn,
                    "subpages_split": huge_len
                }
            else:
                log["details"] = {
                    "status": "SPLIT_ERROR_NOT_HUGE_PAGE",
                    "pfn": pfn
                }

        elif op == "FREE_PAGES":
            freed = 0
            pfns_to_free = cmd.get("pfns", [])
            for pfn in pfns_to_free:
                if 0 <= pfn < total_pages and pages[pfn]["state"] == "ALLOCATED":
                    pages[pfn]["state"] = "FREE"
                    pages[pfn]["page_type"] = "REGULAR_4K"
                    pages[pfn]["vma_id"] = None
                    pages[pfn]["refcount"] = 0
                    pages[pfn]["movable"] = True
                    freed += 1

            log["details"] = {"freed_pages_count": freed}

        cmd_logs.append(log)

    total_free = sum(1 for p in pages if p["state"] == "FREE")
    total_allocated = total_pages - total_free
    current_thps = sum(1 for p in pages if p["page_type"] == "HUGE_2M_HEAD")

    output = {
        "summary": {
            "total_pages": total_pages,
            "hugepage_len": huge_len,
            "free_pages_count": total_free,
            "allocated_pages_count": total_allocated,
            "active_thp_count": current_thps,
            "compaction_runs": compaction_runs,
            "pages_migrated_total": pages_migrated_total,
            "pmd_splits_count": pmd_splits_count
        },
        "command_history": cmd_logs
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    solve()
