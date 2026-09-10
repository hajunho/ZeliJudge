# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #434 Solution:
Linux Kernel Virtual Memory: mm/damon/lru_sort.c Proactive LRU Aging & Sorting Engine
(mm/damon/lru_sort.c, mm/damon/core.c, CONFIG_DAMON_LRU_SORT)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class DamonRegion:
    def __init__(self, region_id, start_addr, end_addr, nr_pages, initial_lru="INACTIVE"):
        self.region_id = region_id
        self.start_addr = start_addr
        self.end_addr = end_addr
        self.nr_pages = nr_pages
        self.current_lru = initial_lru
        self.access_count = 0
        self.age = 0


class DamonLruSortEngine:
    def __init__(self, config):
        self.hot_thres = config.get("hot_thres", 10)
        self.cold_min_age = config.get("cold_min_age", 5)
        self.size_quota_pages = config.get("size_quota_pages", 100)
        
        self.regions = {}
        for r_data in config.get("initial_regions", []):
            rid = r_data["region_id"]
            self.regions[rid] = DamonRegion(
                rid,
                r_data["start_addr"],
                r_data["end_addr"],
                r_data["nr_pages"],
                r_data.get("initial_lru", "INACTIVE")
            )
            
        self.hot_promotions = 0
        self.cold_demotions = 0
        self.quota_throttled_events = 0
        self.total_reclaims = 0
        self.reclaimed_pages = 0
        self.fastpath_reclaim_hits = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "SAMPLE_ACCESS":
            return self._sample_access(cmd)
        elif op == "AGGREGATE_INTERVAL":
            return self._aggregate_interval(cmd)
        elif op == "APPLY_LRU_SORT":
            return self._apply_lru_sort(cmd)
        elif op == "RECLAIM_PAGES":
            return self._reclaim_pages(cmd)
        elif op == "GET_STATISTICS":
            return self._get_statistics(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _sample_access(self, cmd):
        samples = cmd.get("samples", {})
        for rid, count in samples.items():
            if rid in self.regions:
                self.regions[rid].access_count += count
        return {
            "op": "SAMPLE_ACCESS",
            "status": "SAMPLES_RECORDED",
            "sampled_regions": len(samples)
        }

    def _aggregate_interval(self, cmd):
        for reg in self.regions.values():
            if reg.access_count == 0:
                reg.age += 1
            else:
                reg.age = 0
        return {
            "op": "AGGREGATE_INTERVAL",
            "status": "AGGREGATED",
            "region_count": len(self.regions)
        }

    def _apply_lru_sort(self, cmd):
        quota_remaining = self.size_quota_pages
        actions = []
        
        # Hot regions promotion
        for rid, reg in sorted(self.regions.items()):
            if reg.access_count >= self.hot_thres and reg.current_lru != "ACTIVE":
                if quota_remaining >= reg.nr_pages:
                    reg.current_lru = "ACTIVE"
                    quota_remaining -= reg.nr_pages
                    self.hot_promotions += 1
                    actions.append({"region_id": rid, "action": "PROACTIVELY_ACTIVATED", "pages": reg.nr_pages})
                else:
                    self.quota_throttled_events += 1
                    actions.append({"region_id": rid, "action": "HOT_THROTTLED_BY_QUOTA"})
            reg.access_count = 0

        # Cold regions demotion
        for rid, reg in sorted(self.regions.items()):
            if reg.access_count == 0 and reg.age >= self.cold_min_age and reg.current_lru != "INACTIVE":
                if quota_remaining >= reg.nr_pages:
                    reg.current_lru = "INACTIVE"
                    quota_remaining -= reg.nr_pages
                    self.cold_demotions += 1
                    actions.append({"region_id": rid, "action": "PROACTIVELY_DEACTIVATED", "pages": reg.nr_pages})
                else:
                    self.quota_throttled_events += 1
                    actions.append({"region_id": rid, "action": "COLD_THROTTLED_BY_QUOTA"})

        return {
            "op": "APPLY_LRU_SORT",
            "status": "SORTED",
            "actions": actions,
            "quota_remaining": quota_remaining
        }

    def _reclaim_pages(self, cmd):
        target_pages = cmd.get("nr_to_reclaim", 50)
        reclaimed = 0
        reclaimed_regions = []
        
        for rid, reg in sorted(self.regions.items()):
            if reg.current_lru == "INACTIVE" and reclaimed < target_pages and reg.nr_pages > 0:
                pages_from_reg = min(target_pages - reclaimed, reg.nr_pages)
                reclaimed += pages_from_reg
                self.fastpath_reclaim_hits += 1
                reclaimed_regions.append({"region_id": rid, "reclaimed": pages_from_reg, "from_lru": "INACTIVE"})
                reg.nr_pages -= pages_from_reg
                
        if reclaimed < target_pages:
            for rid, reg in sorted(self.regions.items()):
                if reg.current_lru == "ACTIVE" and reg.nr_pages > 0 and reclaimed < target_pages:
                    pages_from_reg = min(target_pages - reclaimed, reg.nr_pages)
                    reclaimed += pages_from_reg
                    reclaimed_regions.append({"region_id": rid, "reclaimed": pages_from_reg, "from_lru": "ACTIVE"})
                    reg.nr_pages -= pages_from_reg

        self.total_reclaims += 1
        self.reclaimed_pages += reclaimed

        return {
            "op": "RECLAIM_PAGES",
            "status": "RECLAIM_COMPLETED",
            "target_pages": target_pages,
            "reclaimed_pages": reclaimed,
            "details": reclaimed_regions
        }

    def _get_statistics(self, cmd):
        active_pages = sum(r.nr_pages for r in self.regions.values() if r.current_lru == "ACTIVE")
        inactive_pages = sum(r.nr_pages for r in self.regions.values() if r.current_lru == "INACTIVE")
        return {
            "op": "GET_STATISTICS",
            "active_pages": active_pages,
            "inactive_pages": inactive_pages,
            "hot_promotions": self.hot_promotions,
            "cold_demotions": self.cold_demotions,
            "quota_throttled_events": self.quota_throttled_events,
            "fastpath_reclaim_hits": self.fastpath_reclaim_hits,
            "total_reclaimed_pages": self.reclaimed_pages
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "hot_promotions": self.hot_promotions,
            "cold_demotions": self.cold_demotions,
            "quota_throttled_events": self.quota_throttled_events,
            "fastpath_reclaim_hits": self.fastpath_reclaim_hits,
            "total_reclaims": self.total_reclaims,
            "reclaimed_pages": self.reclaimed_pages,
            "final_active_pages": sum(r.nr_pages for r in self.regions.values() if r.current_lru == "ACTIVE"),
            "final_inactive_pages": sum(r.nr_pages for r in self.regions.values() if r.current_lru == "INACTIVE")
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = DamonLruSortEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
