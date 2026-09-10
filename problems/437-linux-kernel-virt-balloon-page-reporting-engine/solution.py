# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #437 Solution:
Linux Kernel Virtualization: mm/page_reporting.c & virtio_balloon Free Page Reporting & Page Poisoning Engine
(mm/page_reporting.c, drivers/virtio/virtio_balloon.c, CONFIG_PAGE_REPORTING)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class PageReportingEngine:
    def __init__(self, config):
        self.page_size = config.get("page_size", 4096)
        self.min_order = config.get("min_order", 9)
        self.batch_capacity = config.get("batch_capacity", 16)
        self.poison_check_enabled = config.get("poison_check", True)
        self.guest_poison_val = config.get("guest_poison_val", 0x00)
        self.host_supports_poison = config.get("host_supports_poison", True)
        
        self.backlog = []
        self.reported_ranges = []
        self.active_allocations = {}
        
        self.total_reported_pages = 0
        self.host_reclaimed_bytes = 0
        self.poison_violations = 0
        self.virtqueue_kicks = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "BUDDY_FREE":
            return self._buddy_free(cmd)
        elif op == "PROCESS_REPORTING":
            return self._process_reporting(cmd)
        elif op == "BUDDY_ALLOC":
            return self._buddy_alloc(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _buddy_free(self, cmd):
        pfn = cmd["pfn"]
        order = cmd["order"]
        nr_pages = 1 << order
        poison = cmd.get("poison", self.guest_poison_val)
        
        is_eligible = (order >= self.min_order)
        if is_eligible:
            self.backlog.append({
                "pfn": pfn,
                "nr_pages": nr_pages,
                "poison": poison
            })
            status = "QUEUED_FOR_REPORTING"
        else:
            status = "BELOW_MIN_ORDER_IGNORED"

        return {
            "op": "BUDDY_FREE",
            "pfn": pfn,
            "order": order,
            "nr_pages": nr_pages,
            "status": status,
            "backlog_count": len(self.backlog)
        }

    def _process_reporting(self, cmd):
        if not self.backlog:
            return {
                "op": "PROCESS_REPORTING",
                "status": "BACKLOG_EMPTY",
                "reported_entries": 0
            }

        batch = []
        while self.backlog and len(batch) < self.batch_capacity:
            batch.append(self.backlog.pop(0))

        self.virtqueue_kicks += 1
        reported_pages = 0
        reclaimed_bytes = 0
        violations = 0

        for entry in batch:
            pfn = entry["pfn"]
            nr = entry["nr_pages"]
            poison = entry["poison"]

            if poison != 0x00 and not self.host_supports_poison:
                violations += 1
                self.poison_violations += 1
                self.reported_ranges.append({"pfn": pfn, "nr_pages": nr, "host_reclaimed": False})
            else:
                reported_pages += nr
                reclaimed_bytes += (nr * self.page_size)
                self.reported_ranges.append({"pfn": pfn, "nr_pages": nr, "host_reclaimed": True})

        self.total_reported_pages += reported_pages
        self.host_reclaimed_bytes += reclaimed_bytes

        return {
            "op": "PROCESS_REPORTING",
            "status": "REPORTING_COMPLETED",
            "entries_processed": len(batch),
            "pages_reported": reported_pages,
            "reclaimed_bytes": reclaimed_bytes,
            "poison_violations": violations,
            "remaining_backlog": len(self.backlog)
        }

    def _buddy_alloc(self, cmd):
        handle_id = cmd["handle_id"]
        order = cmd["order"]
        nr_pages = 1 << order
        
        target_range = None
        for r in self.reported_ranges:
            if r["nr_pages"] >= nr_pages:
                target_range = r
                break

        if target_range:
            pfn = target_range["pfn"]
            target_range["pfn"] += nr_pages
            target_range["nr_pages"] -= nr_pages
            if target_range["nr_pages"] == 0:
                self.reported_ranges.remove(target_range)
            status = "ALLOCATED_FROM_REPORTED"
            from_reported = True
        else:
            pfn = 1000000 + (len(self.active_allocations) * 1024)
            status = "ALLOCATED_FRESH"
            from_reported = False

        self.active_allocations[handle_id] = {"pfn": pfn, "nr_pages": nr_pages}

        return {
            "op": "BUDDY_ALLOC",
            "handle_id": handle_id,
            "pfn": pfn,
            "order": order,
            "nr_pages": nr_pages,
            "status": status,
            "from_reported_range": from_reported
        }

    def _get_stats(self, cmd):
        return {
            "op": "GET_STATS",
            "total_reported_pages": self.total_reported_pages,
            "host_reclaimed_bytes": self.host_reclaimed_bytes,
            "backlog_entries": len(self.backlog),
            "active_reported_ranges": len(self.reported_ranges),
            "poison_violations": self.poison_violations,
            "virtqueue_kicks": self.virtqueue_kicks
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "total_reported_pages": self.total_reported_pages,
            "host_reclaimed_bytes": self.host_reclaimed_bytes,
            "poison_violations": self.poison_violations,
            "virtqueue_kicks": self.virtqueue_kicks,
            "final_backlog_entries": len(self.backlog),
            "final_reported_ranges": len(self.reported_ranges)
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = PageReportingEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
