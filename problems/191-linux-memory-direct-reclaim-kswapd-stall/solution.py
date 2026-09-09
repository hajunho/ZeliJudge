# scratch/sim_191.py
import json
import math
import sys
from typing import Dict, List, Any, Optional

class LinuxZoneWatermarkSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.total_mem_mb = sys_cfg.get("total_memory_mb", 4096)
        self.page_size_kb = sys_cfg.get("page_size_kb", 4)
        self.total_pages = int(self.total_mem_mb * 1024 / self.page_size_kb)

        self.min_free_kbytes = sys_cfg.get("min_free_kbytes", 67584)
        self.watermark_scale_factor = sys_cfg.get("watermark_scale_factor", 10) # 10 = 0.1%

        # Calculate exact Linux kernel watermarks (mm/page_alloc.c)
        self.wmark_min = int(self.min_free_kbytes / self.page_size_kb)
        scale_buffer = int(self.total_pages * self.watermark_scale_factor / 10000)
        wmark_delta = max(int(self.wmark_min / 4), scale_buffer)
        self.wmark_low = self.wmark_min + wmark_delta
        self.wmark_high = self.wmark_min + 2 * wmark_delta

        init_free_mb = sys_cfg.get("initial_free_mb", 200)
        self.free_pages = int(init_free_mb * 1024 / self.page_size_kb)
        init_cache_mb = sys_cfg.get("initial_page_cache_mb", 3000)
        self.reclaimable_pages = int(init_cache_mb * 1024 / self.page_size_kb)

        self.kswapd_rate_per_ms = sys_cfg.get("kswapd_rate_pages_per_ms", 5000)
        self.direct_reclaim_cost_us = sys_cfg.get("direct_reclaim_cost_per_page_us", 0.5)

        self.events_input = data.get("workload", [])
        self.current_time_ms = 0.0

        # Metrics
        self.total_allocations = 0
        self.fast_path_allocations = 0
        self.kswapd_wakeups = 0
        self.direct_reclaim_stalls = 0
        self.max_stall_latency_ms = 0.0
        self.total_pages_reclaimed_kswapd = 0
        self.total_pages_reclaimed_direct = 0
        self.oom_killer_invocations = 0

        self.log = []

    def _step_kswapd(self, time_delta_ms: float):
        if time_delta_ms <= 0:
            return
        if self.free_pages < self.wmark_high and self.reclaimable_pages > 0:
            pages_needed = self.wmark_high - self.free_pages
            reclaim_capacity = int(self.kswapd_rate_per_ms * time_delta_ms)
            to_reclaim = min(pages_needed, reclaim_capacity, self.reclaimable_pages)
            if to_reclaim > 0:
                self.reclaimable_pages -= to_reclaim
                self.free_pages += to_reclaim
                self.total_pages_reclaimed_kswapd += to_reclaim

    def run(self) -> Dict[str, Any]:
        for item in self.events_input:
            target_time = item.get("timestamp_ms", self.current_time_ms)
            if target_time > self.current_time_ms:
                self._step_kswapd(target_time - self.current_time_ms)
                self.current_time_ms = target_time

            ev_type = item.get("type", "ALLOC")
            if ev_type == "ALLOC":
                self.total_allocations += 1
                alloc_mb = item.get("size_mb", 0.0)
                alloc_pages = int(alloc_mb * 1024 / self.page_size_kb)
                caller = item.get("caller", "app_thread")

                latency_ms = 0.001 # 1us base alloc time

                # Linux page allocation logic:
                # 1. Fast path: check if free_pages - alloc_pages > wmark_low
                if self.free_pages - alloc_pages > self.wmark_low:
                    self.free_pages -= alloc_pages
                    self.fast_path_allocations += 1
                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "ALLOC_FAST_PATH",
                        "caller": caller,
                        "pages": alloc_pages,
                        "free_pages": self.free_pages,
                        "latency_ms": round(latency_ms, 4)
                    })
                # 2. Slow path async: WMARK_MIN < free_pages - alloc_pages <= WMARK_LOW
                elif self.free_pages - alloc_pages > self.wmark_min:
                    self.free_pages -= alloc_pages
                    self.kswapd_wakeups += 1
                    # User thread is NOT stalled, kswapd is triggered
                    latency_ms = 0.005 # 5us
                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "ALLOC_KSWAPD_ASYNC_WAKEUP",
                        "caller": caller,
                        "pages": alloc_pages,
                        "free_pages": self.free_pages,
                        "latency_ms": round(latency_ms, 4)
                    })
                # 3. Direct Reclaim catastrophe: free_pages - alloc_pages <= WMARK_MIN
                else:
                    pages_deficit = (self.wmark_low - (self.free_pages - alloc_pages))
                    pages_to_reclaim = min(pages_deficit, self.reclaimable_pages)

                    if self.free_pages + pages_to_reclaim - alloc_pages < self.wmark_min:
                        # Cannot even satisfy allocation with reclaim -> OOM!
                        self.oom_killer_invocations += 1
                        self.log.append({
                            "time_ms": self.current_time_ms,
                            "event": "OOM_KILLER_TRIGGERED",
                            "caller": caller,
                            "deficit_pages": pages_deficit
                        })
                        break

                    # User thread is synchronously frozen in direct reclaim!
                    self.direct_reclaim_stalls += 1
                    stall_duration_ms = (pages_to_reclaim * self.direct_reclaim_cost_us) / 1000.0
                    latency_ms = stall_duration_ms
                    self.max_stall_latency_ms = max(self.max_stall_latency_ms, latency_ms)

                    self.reclaimable_pages -= pages_to_reclaim
                    self.free_pages = (self.free_pages + pages_to_reclaim) - alloc_pages
                    self.total_pages_reclaimed_direct += pages_to_reclaim

                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "DIRECT_RECLAIM_STALL",
                        "caller": caller,
                        "pages_reclaimed": pages_to_reclaim,
                        "free_pages": self.free_pages,
                        "stall_latency_ms": round(latency_ms, 3)
                    })

            elif ev_type == "FREE":
                free_mb = item.get("size_mb", 0.0)
                freed_pages = int(free_mb * 1024 / self.page_size_kb)
                self.free_pages += freed_pages

        # Determine verdict
        if self.oom_killer_invocations > 0:
            status = "FAILED"
            verdict = "OOM_KILLER_INVOKED_DISASTER"
        elif self.direct_reclaim_stalls > 0:
            status = "FAILED"
            verdict = "DIRECT_RECLAIM_LATENCY_STALL_DISASTER"
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_ASYNC_KSWAPD_RECLAIM"

        return {
            "status": status,
            "watermarks": {
                "wmark_min_pages": self.wmark_min,
                "wmark_low_pages": self.wmark_low,
                "wmark_high_pages": self.wmark_high,
                "buffer_pages": self.wmark_low - self.wmark_min
            },
            "metrics": {
                "total_allocations": self.total_allocations,
                "fast_path_allocations": self.fast_path_allocations,
                "kswapd_wakeups": self.kswapd_wakeups,
                "direct_reclaim_stalls": self.direct_reclaim_stalls,
                "max_stall_latency_ms": round(self.max_stall_latency_ms, 2),
                "total_pages_reclaimed_kswapd": self.total_pages_reclaimed_kswapd,
                "total_pages_reclaimed_direct": self.total_pages_reclaimed_direct,
                "oom_killer_invocations": self.oom_killer_invocations,
                "verdict": verdict
            },
            "events_log": self.log
        }

if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    sim = LinuxZoneWatermarkSimulator(input_data)
    res = sim.run()
    print(json.dumps(res, indent=2))
