# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #445 Solution:
Linux Kernel Real-Time Scheduling: kernel/sched/deadline.c SCHED_DEADLINE GRUB Bandwidth Reclamation
(kernel/sched/deadline.c, include/linux/sched.h, kernel/sched/sched.h)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class SchedDeadlineGrubEngine:
    def __init__(self, config):
        self.u_max = config.get("u_max", 0.95)
        self.grub_enabled = config.get("grub_enabled", True)
        
        self.tasks = {}
        self.u_act = 0.0
        self.current_time = 0
        
        self.total_exec_time_us = 0
        self.total_budget_consumed_us = 0
        self.reclaimed_bandwidth_us = 0
        self.zero_lag_firings = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "ENQUEUE_TASK":
            return self._enqueue_task(cmd)
        elif op == "STEP_RUN":
            return self._step_run(cmd)
        elif op == "BLOCK_TASK":
            return self._block_task(cmd)
        elif op == "TIMER_TICK":
            return self._timer_tick(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _update_zero_lag_timers(self, new_time):
        self.current_time = new_time
        fired = []
        for tid, t in self.tasks.items():
            if t["state"] == "INACTIVE_TIMER" and self.current_time >= t["zero_lag_time"]:
                t["state"] = "INACTIVE_IDLE"
                self.u_act = max(0.0, self.u_act - t["util"])
                self.zero_lag_firings += 1
                fired.append(tid)
        return fired

    def _enqueue_task(self, cmd):
        tid = cmd["task_id"]
        runtime = cmd["runtime"]
        deadline = cmd["deadline"]
        period = cmd["period"]
        timestamp = cmd.get("timestamp", self.current_time)
        
        self._update_zero_lag_timers(timestamp)
        
        util = runtime / period
        d_val = timestamp + deadline
        
        self.tasks[tid] = {
            "task_id": tid,
            "runtime": runtime,
            "deadline": deadline,
            "period": period,
            "util": util,
            "cur_budget": runtime,
            "cur_deadline": d_val,
            "state": "RUNNABLE",
            "zero_lag_time": 0
        }
        self.u_act += util
        
        return {
            "op": "ENQUEUE_TASK",
            "task_id": tid,
            "util": round(util, 4),
            "cur_budget": runtime,
            "cur_deadline": d_val,
            "u_act": round(self.u_act, 4),
            "status": "TASK_ENQUEUED"
        }

    def _step_run(self, cmd):
        tid = cmd["task_id"]
        elapsed = cmd["elapsed_us"]
        timestamp = cmd.get("timestamp", self.current_time + elapsed)
        
        if tid not in self.tasks:
            return {"op": "STEP_RUN", "task_id": tid, "status": "NOT_FOUND"}
            
        t = self.tasks[tid]
        
        if self.grub_enabled:
            scale_factor = max(t["util"], self.u_act)
            dq = int(round(scale_factor * elapsed))
        else:
            dq = elapsed
            
        dq = min(t["cur_budget"], dq)
        t["cur_budget"] -= dq
        
        self.total_exec_time_us += elapsed
        self.total_budget_consumed_us += dq
        self.reclaimed_bandwidth_us += max(0, elapsed - dq)
        
        fired = self._update_zero_lag_timers(timestamp)
        
        return {
            "op": "STEP_RUN",
            "task_id": tid,
            "elapsed_us": elapsed,
            "budget_consumed": dq,
            "remaining_budget": t["cur_budget"],
            "u_act": round(self.u_act, 4),
            "reclaimed_us": max(0, elapsed - dq),
            "status": "STEP_COMPLETED"
        }

    def _block_task(self, cmd):
        tid = cmd["task_id"]
        timestamp = cmd.get("timestamp", self.current_time)
        
        if tid not in self.tasks:
            return {"op": "BLOCK_TASK", "task_id": tid, "status": "NOT_FOUND"}
            
        t = self.tasks[tid]
        t_zero_lag = int(round(t["cur_deadline"] - (t["cur_budget"] / t["util"])))
        t["zero_lag_time"] = t_zero_lag
        t["state"] = "INACTIVE_TIMER"
        
        self._update_zero_lag_timers(timestamp)
        
        return {
            "op": "BLOCK_TASK",
            "task_id": tid,
            "zero_lag_time": t_zero_lag,
            "remaining_budget": t["cur_budget"],
            "u_act": round(self.u_act, 4),
            "status": "TASK_BLOCKED_INACTIVE"
        }

    def _timer_tick(self, cmd):
        timestamp = cmd["timestamp"]
        fired = self._update_zero_lag_timers(timestamp)
        return {
            "op": "TIMER_TICK",
            "current_time": self.current_time,
            "zero_lag_fired_tasks": fired,
            "u_act": round(self.u_act, 4)
        }

    def _get_stats(self, cmd):
        return {
            "op": "GET_STATS",
            "grub_enabled": self.grub_enabled,
            "u_act": round(self.u_act, 4),
            "total_exec_time_us": self.total_exec_time_us,
            "total_budget_consumed_us": self.total_budget_consumed_us,
            "reclaimed_bandwidth_us": self.reclaimed_bandwidth_us,
            "zero_lag_firings": self.zero_lag_firings
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "grub_enabled": self.grub_enabled,
            "u_act": round(self.u_act, 4),
            "total_exec_time_us": self.total_exec_time_us,
            "total_budget_consumed_us": self.total_budget_consumed_us,
            "reclaimed_bandwidth_us": self.reclaimed_bandwidth_us,
            "zero_lag_firings": self.zero_lag_firings
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = SchedDeadlineGrubEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
