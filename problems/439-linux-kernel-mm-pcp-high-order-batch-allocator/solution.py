# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #439 Solution:
Linux Kernel Memory Management: mm/page_alloc.c High-Order Per-CPU Page Sets (PCP) Batch Refill & Drain Engine
(mm/page_alloc.c, include/linux/mmzone.h, mm/vmstat.c)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class HighOrderPcpEngine:
    def __init__(self, config):
        self.num_cpus = config.get("num_cpus", 4)
        self.max_pcp_order = config.get("max_pcp_order", 3)
        self.batch = config.get("batch", 4)
        self.high_watermark = config.get("high_watermark", 12)
        self.zone_pfn_start = config.get("zone_pfn_start", 0x10000)
        
        self.zone_lock_count = 0
        self.next_zone_pfn = self.zone_pfn_start
        self.zone_free_lists = {o: [] for o in range(self.max_pcp_order + 1)}
        
        self.cpus = {}
        for c in range(self.num_cpus):
            self.cpus[c] = {
                "lists": {o: [] for o in range(self.max_pcp_order + 1)},
                "count": 0,
                "local_hits": 0,
                "bulk_refills": 0,
                "bulk_drains": 0,
                "zone_lock_acquisitions": 0
            }
            
        self.active_allocations = {}
        
        for o in range(self.max_pcp_order + 1):
            for _ in range(8):
                pfn = self._alloc_zone_raw(o)
                self.zone_free_lists[o].append({"pfn": pfn, "order": o})

    def _alloc_zone_raw(self, order):
        pfn = self.next_zone_pfn
        self.next_zone_pfn += (1 << order)
        return pfn

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "PCP_ALLOC":
            return self._pcp_alloc(cmd)
        elif op == "PCP_FREE":
            return self._pcp_free(cmd)
        elif op == "DRAIN_CPU":
            return self._drain_cpu(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _pcp_alloc(self, cmd):
        cpu_id = cmd["cpu_id"]
        order = cmd["order"]
        handle_id = cmd["handle_id"]
        
        if cpu_id not in self.cpus or order > self.max_pcp_order:
            return {"op": "PCP_ALLOC", "status": "EINVAL"}
            
        cpu = self.cpus[cpu_id]
        order_list = cpu["lists"][order]
        
        if len(order_list) > 0:
            blk = order_list.pop()
            cpu["count"] -= 1
            cpu["local_hits"] += 1
            status = "ALLOC_PCP_HIT"
            lock_acquired = False
        else:
            self.zone_lock_count += 1
            cpu["zone_lock_acquisitions"] += 1
            cpu["bulk_refills"] += 1
            lock_acquired = True
            
            fetched = []
            while len(fetched) < self.batch:
                if self.zone_free_lists[order]:
                    fetched.append(self.zone_free_lists[order].pop(0))
                else:
                    pfn = self._alloc_zone_raw(order)
                    fetched.append({"pfn": pfn, "order": order})
                    
            blk = fetched.pop(0)
            for b in fetched:
                order_list.append(b)
                cpu["count"] += 1
            status = "ALLOC_PCP_REFILL"
            
        self.active_allocations[handle_id] = {
            "pfn": blk["pfn"],
            "order": order,
            "allocated_by_cpu": cpu_id
        }
        
        return {
            "op": "PCP_ALLOC",
            "cpu_id": cpu_id,
            "handle_id": handle_id,
            "order": order,
            "pfn": blk["pfn"],
            "status": status,
            "lock_acquired": lock_acquired,
            "cpu_pcp_count": cpu["count"]
        }

    def _pcp_free(self, cmd):
        cpu_id = cmd["cpu_id"]
        handle_id = cmd["handle_id"]
        
        if handle_id not in self.active_allocations or cpu_id not in self.cpus:
            return {"op": "PCP_FREE", "status": "NOT_FOUND"}
            
        info = self.active_allocations.pop(handle_id)
        order = info["order"]
        pfn = info["pfn"]
        
        cpu = self.cpus[cpu_id]
        blk = {"pfn": pfn, "order": order}
        
        cpu["lists"][order].append(blk)
        cpu["count"] += 1
        
        if cpu["count"] >= self.high_watermark:
            self.zone_lock_count += 1
            cpu["zone_lock_acquisitions"] += 1
            cpu["bulk_drains"] += 1
            lock_acquired = True
            
            drained = 0
            orders_to_check = [order] + [o for o in range(self.max_pcp_order + 1) if o != order]
            for o in orders_to_check:
                while cpu["lists"][o] and drained < self.batch:
                    b = cpu["lists"][o].pop(0)
                    self.zone_free_lists[o].append(b)
                    cpu["count"] -= 1
                    drained += 1
                if drained >= self.batch:
                    break
            status = "FREE_PCP_DRAINED"
        else:
            lock_acquired = False
            status = "FREE_PCP_CACHED"
            
        return {
            "op": "PCP_FREE",
            "cpu_id": cpu_id,
            "handle_id": handle_id,
            "order": order,
            "pfn": pfn,
            "status": status,
            "lock_acquired": lock_acquired,
            "cpu_pcp_count": cpu["count"]
        }

    def _drain_cpu(self, cmd):
        cpu_id = cmd["cpu_id"]
        if cpu_id not in self.cpus:
            return {"op": "DRAIN_CPU", "status": "EINVAL"}
            
        cpu = self.cpus[cpu_id]
        drained_count = 0
        if cpu["count"] > 0:
            self.zone_lock_count += 1
            cpu["zone_lock_acquisitions"] += 1
            for o in range(self.max_pcp_order + 1):
                while cpu["lists"][o]:
                    b = cpu["lists"][o].pop(0)
                    self.zone_free_lists[o].append(b)
                    drained_count += 1
            cpu["count"] = 0
            
        return {
            "op": "DRAIN_CPU",
            "cpu_id": cpu_id,
            "drained_blocks": drained_count,
            "status": "CPU_PCP_DRAINED_ALL"
        }

    def _get_stats(self, cmd):
        cpus_stat = {}
        for c in range(self.num_cpus):
            cpu = self.cpus[c]
            cpus_stat[str(c)] = {
                "count": cpu["count"],
                "local_hits": cpu["local_hits"],
                "bulk_refills": cpu["bulk_refills"],
                "bulk_drains": cpu["bulk_drains"],
                "zone_lock_acquisitions": cpu["zone_lock_acquisitions"]
            }
        return {
            "op": "GET_STATS",
            "zone_lock_count": self.zone_lock_count,
            "active_allocations": len(self.active_allocations),
            "cpus": cpus_stat
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        total_hits = sum(c["local_hits"] for c in self.cpus.values())
        total_refills = sum(c["bulk_refills"] for c in self.cpus.values())
        total_drains = sum(c["bulk_drains"] for c in self.cpus.values())
        total_pcp_blocks = sum(c["count"] for c in self.cpus.values())
        
        summary = {
            "zone_lock_count": self.zone_lock_count,
            "total_local_hits": total_hits,
            "total_bulk_refills": total_refills,
            "total_bulk_drains": total_drains,
            "active_allocations": len(self.active_allocations),
            "total_pcp_blocks_cached": total_pcp_blocks
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = HighOrderPcpEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
