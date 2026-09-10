import sys
import json
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class CfsRq:
    def __init__(self, cpu_id: int):
        self.cpu_id = cpu_id
        self.runtime_remaining_us = 0
        self.throttled = False

class CfsBandwidthEngine:
    """
    Simulation of Linux kernel/sched/fair.c CFS Bandwidth Controller with Burst (Linux 5.14+):
    - period_us, quota_us, max_burst_us, slice_us, num_cpus
    - Per-CPU cfs_rq slice borrowing
    - Throttling upon global quota exhaustion
    - Period tick: carryover unused quota to burst, replenish, unthrottle all
    """
    def __init__(self, 
                 period_us: int = 100000, 
                 quota_us: int = 100000, 
                 max_burst_us: int = 50000, 
                 slice_us: int = 5000,
                 num_cpus: int = 4):
        self.period_us = period_us
        self.quota_us = quota_us
        self.max_burst_us = max_burst_us
        self.slice_us = slice_us
        self.num_cpus = num_cpus
        
        self.time_us = 0
        self.period_count = 0
        self.current_runtime_us = quota_us
        self.burst_buffer_us = 0
        
        self.cfs_rqs: Dict[int, CfsRq] = {c: CfsRq(c) for c in range(num_cpus)}
        self.nr_throttled = 0
        self.throttled_time_us = 0

    def borrow_slice(self, cpu_id: int) -> bool:
        rq = self.cfs_rqs[cpu_id]
        if self.current_runtime_us <= 0:
            if not rq.throttled:
                rq.throttled = True
                self.nr_throttled += 1
            return False
            
        borrow_amount = min(self.slice_us, self.current_runtime_us)
        self.current_runtime_us -= borrow_amount
        rq.runtime_remaining_us += borrow_amount
        return True

    def run_cpu(self, cpu_id: int, execution_time_us: int) -> Dict[str, Any]:
        rq = self.cfs_rqs[cpu_id]
        if rq.throttled:
            self.throttled_time_us += execution_time_us
            return {
                "cpu_id": cpu_id,
                "executed_us": 0,
                "throttled": True,
                "reason": "RQ_ALREADY_THROTTLED"
            }
            
        executed_so_far = 0
        while executed_so_far < execution_time_us:
            needed = execution_time_us - executed_so_far
            if rq.runtime_remaining_us <= 0:
                if not self.borrow_slice(cpu_id):
                    remaining_unexecuted = execution_time_us - executed_so_far
                    self.throttled_time_us += remaining_unexecuted
                    return {
                        "cpu_id": cpu_id,
                        "executed_us": executed_so_far,
                        "throttled": True,
                        "reason": "GLOBAL_QUOTA_EXHAUSTED"
                    }
                    
            consume = min(needed, rq.runtime_remaining_us)
            rq.runtime_remaining_us -= consume
            executed_so_far += consume
            
        return {
            "cpu_id": cpu_id,
            "executed_us": executed_so_far,
            "throttled": False,
            "reason": "OK"
        }

    def period_tick(self) -> Dict[str, Any]:
        self.time_us += self.period_us
        self.period_count += 1
        
        unused_in_rqs = sum(rq.runtime_remaining_us for rq in self.cfs_rqs.values())
        total_unused = max(0, self.current_runtime_us + unused_in_rqs)
        
        for rq in self.cfs_rqs.values():
            rq.runtime_remaining_us = 0
            rq.throttled = False
            
        self.burst_buffer_us = min(self.max_burst_us, self.burst_buffer_us + total_unused)
        assigned_burst = self.burst_buffer_us
        self.current_runtime_us = self.quota_us + assigned_burst
        self.burst_buffer_us = 0
        
        return {
            "period_count": self.period_count,
            "replenished_runtime_us": self.current_runtime_us,
            "assigned_burst_us": assigned_burst,
            "all_unthrottled": True
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            "time_us": self.time_us,
            "period_count": self.period_count,
            "global_runtime_remaining_us": self.current_runtime_us,
            "nr_throttled": self.nr_throttled,
            "throttled_time_us": self.throttled_time_us,
            "throttled_rq_cpus": [c for c, rq in self.cfs_rqs.items() if rq.throttled]
        }

def process_trace(data: Dict[str, Any]) -> Dict[str, Any]:
    period_us = data.get("period_us", 100000)
    quota_us = data.get("quota_us", 100000)
    max_burst_us = data.get("max_burst_us", 50000)
    slice_us = data.get("slice_us", 5000)
    num_cpus = data.get("num_cpus", 4)
    commands = data.get("commands", [])
    
    engine = CfsBandwidthEngine(period_us, quota_us, max_burst_us, slice_us, num_cpus)
    command_results = []
    
    for cmd in commands:
        op = cmd.get("op")
        if op == "RUN":
            cpu = cmd.get("cpu", 0)
            exec_time = cmd.get("execution_time_us", 1000)
            res = engine.run_cpu(cpu, exec_time)
            command_results.append({"op": "RUN", "result": res})
        elif op == "PERIOD_TICK":
            res = engine.period_tick()
            command_results.append({"op": "PERIOD_TICK", "result": res})
            
    stats = engine.get_stats()
    return {
        "command_results": command_results,
        "final_stats": stats
    }

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    res = process_trace(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
