# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class CFSBandwidthEngine:
    def __init__(self, config=None):
        config = config or {}
        self.period_us = config.get("period_us", 100000)
        self.quota_us = config.get("quota_us", 200000)
        self.slice_us = config.get("slice_us", 5000)
        self.max_burst_us = config.get("burst_us", 0)
        self.num_cpus = config.get("num_cpus", 4)
        self.parent_quota_us = config.get("parent_quota_us")

        self.current_time_us = 0
        self.period_index = 0
        self.runtime_remaining = self.quota_us
        self.burst_buffer = 0
        self.parent_runtime = self.parent_quota_us if self.parent_quota_us is not None else None

        self.cpus = {
            c: {"slice": 0, "throttled": False, "total_executed": 0} for c in range(self.num_cpus)
        }

        self.stats = {
            "periods": 0,
            "nr_throttled": 0,
            "throttled_time_us": 0,
            "total_runtime_consumed": 0,
            "burst_used_us": 0
        }
        self.history = []

    def _on_period_expire(self):
        self.stats["periods"] += 1
        self.period_index += 1

        if self.max_burst_us > 0 and self.runtime_remaining > 0:
            accumulated = min(self.max_burst_us, self.burst_buffer + self.runtime_remaining)
            self.burst_buffer = accumulated
        elif self.runtime_remaining <= 0:
            self.burst_buffer = 0

        self.runtime_remaining = self.quota_us + self.burst_buffer
        if self.parent_quota_us is not None:
            self.parent_runtime = self.parent_quota_us

        unthrottled = []
        for c in range(self.num_cpus):
            if self.cpus[c]["throttled"]:
                self.cpus[c]["throttled"] = False
                unthrottled.append(c)

        self.history.append({
            "time_us": self.current_time_us,
            "event": "PERIOD_EXPIRED_REFILL",
            "period": self.period_index,
            "refilled_runtime": self.runtime_remaining,
            "burst_buffer": self.burst_buffer,
            "unthrottled_cpus": unthrottled
        })

    def advance_time_to(self, target_time_us):
        while self.current_time_us + (self.period_us - (self.current_time_us % self.period_us)) <= target_time_us:
            next_boundary = self.current_time_us + (self.period_us - (self.current_time_us % self.period_us))
            if next_boundary == self.current_time_us:
                next_boundary += self.period_us
            self.current_time_us = next_boundary
            self._on_period_expire()
        self.current_time_us = target_time_us

    def step(self, action):
        target_time = action.get("time_us", self.current_time_us)
        if target_time > self.current_time_us:
            self.advance_time_to(target_time)

        act_type = action.get("type")
        if act_type == "RUN_TASK":
            cpu_id = action.get("cpu_id", 0)
            req_duration = action.get("duration_us", 0)
            cpu = self.cpus[cpu_id]

            if cpu["throttled"]:
                self.stats["throttled_time_us"] += req_duration
                res = {
                    "time_us": self.current_time_us,
                    "event": "TASK_EXEC",
                    "cpu_id": cpu_id,
                    "requested_us": req_duration,
                    "executed_us": 0,
                    "status": "THROTTLED"
                }
                self.history.append(res)
                return res

            remaining = req_duration
            executed = 0

            while remaining > 0:
                if cpu["slice"] >= remaining:
                    cpu["slice"] -= remaining
                    executed += remaining
                    remaining = 0
                    break
                else:
                    executed += cpu["slice"]
                    remaining -= cpu["slice"]
                    cpu["slice"] = 0

                    if self.runtime_remaining <= 0 or (self.parent_runtime is not None and self.parent_runtime <= 0):
                        cpu["throttled"] = True
                        self.stats["nr_throttled"] += 1
                        self.stats["throttled_time_us"] += remaining
                        break

                    claim = min(self.slice_us, self.runtime_remaining)
                    if self.parent_runtime is not None:
                        claim = min(claim, self.parent_runtime)
                        self.parent_runtime -= claim

                    if self.runtime_remaining > self.quota_us:
                        from_burst = min(claim, self.runtime_remaining - self.quota_us)
                        self.stats["burst_used_us"] += from_burst

                    self.runtime_remaining -= claim
                    cpu["slice"] += claim

            cpu["total_executed"] += executed
            self.stats["total_runtime_consumed"] += executed

            status = "COMPLETED" if remaining == 0 else "PARTIALLY_THROTTLED"
            res = {
                "time_us": self.current_time_us,
                "event": "TASK_EXEC",
                "cpu_id": cpu_id,
                "requested_us": req_duration,
                "executed_us": executed,
                "status": status
            }
            self.history.append(res)
            return res

        elif act_type == "ADVANCE_TIME":
            pass

    def run_simulation(self, actions):
        for act in actions:
            self.step(act)

        return {
            "history": self.history,
            "stats": self.stats,
            "final_state": {
                "current_time_us": self.current_time_us,
                "periods_elapsed": self.stats["periods"],
                "runtime_remaining_us": self.runtime_remaining,
                "burst_buffer_us": self.burst_buffer,
                "cpus": {
                    c: {
                        "slice_us": self.cpus[c]["slice"],
                        "throttled": self.cpus[c]["throttled"],
                        "total_executed_us": self.cpus[c]["total_executed"]
                    } for c in range(self.num_cpus)
                }
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    actions = data.get("actions", [])
    engine = CFSBandwidthEngine(config)
    res = engine.run_simulation(actions)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
