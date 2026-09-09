# scratch/sim_194.py
import json
import math
import sys
from typing import Dict, List, Any, Optional

class LinuxCFSThrottlingSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.cfs_period_us = sys_cfg.get("cfs_period_us", 100000) # 100ms = 100,000us
        self.cfs_quota_us = sys_cfg.get("cfs_quota_us", 200000)   # 200ms = 2 cores
        self.cfs_burst_us = sys_cfg.get("cfs_burst_us", 0)        # Linux 5.14+ CFS burst
        self.automaxprocs_enabled = sys_cfg.get("automaxprocs_enabled", False)
        self.physical_cores = sys_cfg.get("node_physical_cores", 8)

        # Calculate effective thread count
        configured_threads = sys_cfg.get("app_thread_count", 8)
        if self.automaxprocs_enabled:
            # Matches quota / period (e.g. 200,000 / 100,000 = 2 threads)
            self.active_threads = max(1, int(self.cfs_quota_us / self.cfs_period_us))
        else:
            # Over-subscribed to host cores (e.g. 8 threads)
            self.active_threads = configured_threads

        # CFS runtime state
        self.current_period_idx = 0
        self.remaining_quota_us = self.cfs_quota_us + self.cfs_burst_us
        self.period_start_time_us = 0.0
        self.current_time_us = 0.0

        self.events_input = data.get("workload", [])

        # Metrics
        self.total_requests = 0
        self.throttled_periods_count = 0
        self.total_throttled_time_us = 0.0
        self.max_request_latency_us = 0.0
        self.completed_requests = 0

        self.log = []

    def _advance_time(self, target_time_us: float):
        while self.current_time_us < target_time_us:
            period_end_us = self.period_start_time_us + self.cfs_period_us
            if target_time_us >= period_end_us:
                # Advance to next period
                self.current_time_us = period_end_us
                self.period_start_time_us = period_end_us
                self.current_period_idx += 1
                self.remaining_quota_us = self.cfs_quota_us + self.cfs_burst_us
            else:
                self.current_time_us = target_time_us
                break

    def run(self) -> Dict[str, Any]:
        for item in self.events_input:
            req_time_us = item.get("timestamp_us", self.current_time_us)
            self._advance_time(req_time_us)

            self.total_requests += 1
            req_id = item.get("request_id", f"req_{self.total_requests}")
            # CPU work needed in total CPU microseconds (e.g., 80,000 us = 80ms CPU work)
            total_cpu_work_us = item.get("cpu_work_us", 80000)

            req_start_us = self.current_time_us
            work_remaining_us = total_cpu_work_us
            req_throttled_time_us = 0.0

            # Process work across threads and CFS periods
            while work_remaining_us > 0:
                # In each wall-clock microsecond, active_threads consume CPU in parallel
                # If remaining_quota_us > 0: can execute
                if self.remaining_quota_us > 0:
                    # Wall clock time until period ends
                    period_remaining_wall_us = (self.period_start_time_us + self.cfs_period_us) - self.current_time_us

                    # Wall clock time needed to finish work with current active threads
                    needed_wall_us = math.ceil(work_remaining_us / self.active_threads)

                    # Max wall clock time allowed by remaining quota
                    allowed_wall_by_quota_us = math.floor(self.remaining_quota_us / self.active_threads)

                    step_wall_us = min(needed_wall_us, period_remaining_wall_us, allowed_wall_by_quota_us)
                    if step_wall_us == 0:
                        step_wall_us = 1 # Progress at least 1us

                    cpu_consumed = min(step_wall_us * self.active_threads, work_remaining_us, self.remaining_quota_us)
                    work_remaining_us -= cpu_consumed
                    self.remaining_quota_us -= cpu_consumed
                    self.current_time_us += step_wall_us

                    if self.current_time_us >= self.period_start_time_us + self.cfs_period_us:
                        # Period expired, reset
                        self.period_start_time_us += self.cfs_period_us
                        self.current_period_idx += 1
                        self.remaining_quota_us = self.cfs_quota_us + self.cfs_burst_us
                else:
                    # THROTTLED! Must wait until next period begins
                    throttle_duration_us = (self.period_start_time_us + self.cfs_period_us) - self.current_time_us
                    self.throttled_periods_count += 1
                    self.total_throttled_time_us += throttle_duration_us
                    req_throttled_time_us += throttle_duration_us

                    self.log.append({
                        "time_us": self.current_time_us,
                        "event": "CFS_THROTTLED_WAIT",
                        "request_id": req_id,
                        "stall_duration_us": throttle_duration_us,
                        "period_idx": self.current_period_idx
                    })

                    # Advance clock to next period
                    self.current_time_us = self.period_start_time_us + self.cfs_period_us
                    self.period_start_time_us = self.current_time_us
                    self.current_period_idx += 1
                    self.remaining_quota_us = self.cfs_quota_us + self.cfs_burst_us

            total_latency_us = self.current_time_us - req_start_us
            self.max_request_latency_us = max(self.max_request_latency_us, total_latency_us)
            self.completed_requests += 1

            self.log.append({
                "time_us": self.current_time_us,
                "event": "REQUEST_COMPLETED",
                "request_id": req_id,
                "latency_us": total_latency_us,
                "throttled_us": req_throttled_time_us
            })

        # Final Verdict
        if self.throttled_periods_count > 0 and not self.automaxprocs_enabled and self.cfs_burst_us == 0:
            status = "FAILED"
            verdict = "CFS_FALSE_THROTTLING_LATENCY_SPIKE_DISASTER"
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_CFS_AUTOMAXPROCS_TUNED"

        return {
            "status": status,
            "system_config": {
                "cfs_period_us": self.cfs_period_us,
                "cfs_quota_us": self.cfs_quota_us,
                "cfs_burst_us": self.cfs_burst_us,
                "active_threads": self.active_threads,
                "automaxprocs_enabled": self.automaxprocs_enabled
            },
            "metrics": {
                "total_requests": self.total_requests,
                "completed_requests": self.completed_requests,
                "throttled_periods_count": self.throttled_periods_count,
                "total_throttled_time_us": self.total_throttled_time_us,
                "max_request_latency_us": self.max_request_latency_us,
                "verdict": verdict
            },
            "events_log": self.log
        }

if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    sim = LinuxCFSThrottlingSimulator(input_data)
    res = sim.run()
    print(json.dumps(res, indent=2))
