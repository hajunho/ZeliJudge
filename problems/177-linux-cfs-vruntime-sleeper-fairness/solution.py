import json
import sys
from typing import Dict, List, Any, Optional

NICE_TO_WEIGHT = {
    -20: 88761, -19: 71755, -18: 56483, -17: 46273, -16: 36291,
    -15: 29154, -14: 23254, -13: 18705, -12: 14949, -11: 11916,
    -10: 9548, -9: 7620, -8: 6100, -7: 4904, -6: 3906,
    -5: 3121, -4: 2501, -3: 1991, -2: 1586, -1: 1277,
    0: 1024, 1: 820, 2: 655, 3: 526, 4: 423,
    5: 335, 6: 272, 7: 215, 8: 172, 9: 137,
    10: 110, 11: 87, 12: 70, 13: 56, 14: 45,
    15: 36, 16: 29, 17: 23, 18: 18, 19: 15
}

class CfsTask:
    def __init__(self, task_id: str, nice: int = 0):
        self.task_id = task_id
        self.nice = max(-20, min(19, nice))
        self.weight = NICE_TO_WEIGHT[self.nice]
        self.vruntime = 0.0
        self.total_exec_time = 0.0
        self.state = "RUNNABLE"  # RUNNABLE, RUNNING, SLEEPING
        self.wake_time: Optional[int] = None
        self.current_wait_time = 0.0
        self.max_wait_latency_ms = 0.0
        self.sleep_count = 0

class CfsSimulator:
    def __init__(self, config: Dict[str, Any]):
        self.sched_latency_ms = config.get("sched_latency_ms", 6.0)
        self.min_granularity_ms = config.get("min_granularity_ms", 1.0)
        self.enable_sleeper_fairness = config.get("enable_sleeper_fairness", True)
        self.min_vruntime = 0.0
        self.tasks: Dict[str, CfsTask] = {}
        self.current_task_id: Optional[str] = None

    def create_task(self, task_id: str, nice: int = 0):
        task = CfsTask(task_id, nice)
        task.vruntime = self.min_vruntime
        self.tasks[task_id] = task

    def simulate(self, events: List[Dict[str, Any]], total_ticks: int) -> Dict[str, Any]:
        events_by_tick: Dict[int, List[Dict[str, Any]]] = {}
        for ev in events:
            t = ev["tick"]
            events_by_tick.setdefault(t, []).append(ev)

        for tick in range(total_ticks):
            # 1. Process scheduled wakeups
            for tid, task in sorted(self.tasks.items()):
                if task.state == "SLEEPING" and task.wake_time is not None and task.wake_time <= tick:
                    self._wakeup_task(tid)

            # 2. Process external events at this tick
            if tick in events_by_tick:
                for ev in events_by_tick[tick]:
                    ev_type = ev["type"]
                    tid = ev["task_id"]
                    if ev_type == "create_task":
                        self.create_task(tid, ev.get("nice", 0))
                    elif ev_type == "sleep":
                        duration = ev.get("duration", 0)
                        self._sleep_task(tid, duration, tick)
                    elif ev_type == "wake":
                        self._wakeup_task(tid)

            # 3. Select next task to run
            runnable_tasks = [t for t in self.tasks.values() if t.state in ("RUNNABLE", "RUNNING")]
            
            chosen_task_id = None
            if runnable_tasks:
                # CFS selection: leftmost vruntime, tie-break deterministically by task_id
                runnable_tasks.sort(key=lambda t: (round(t.vruntime, 6), t.task_id))
                chosen = runnable_tasks[0]
                chosen_task_id = chosen.task_id

                # Update states and execution metrics
                for t in runnable_tasks:
                    if t.task_id == chosen_task_id:
                        t.state = "RUNNING"
                        t.total_exec_time += 1.0
                        t.current_wait_time = 0.0
                        # Advance vruntime: delta * (1024 / weight)
                        vruntime_step = 1.0 * (1024.0 / t.weight)
                        t.vruntime += vruntime_step
                    else:
                        t.state = "RUNNABLE"
                        t.current_wait_time += 1.0
                        t.max_wait_latency_ms = max(t.max_wait_latency_ms, t.current_wait_time)

                # Monotonically advance min_vruntime
                active_vruntimes = [t.vruntime for t in runnable_tasks]
                self.min_vruntime = max(self.min_vruntime, min(active_vruntimes))

            self.current_task_id = chosen_task_id

        return self._summarize_results()

    def _sleep_task(self, task_id: str, duration: int, current_tick: int):
        task = self.tasks[task_id]
        task.state = "SLEEPING"
        task.current_wait_time = 0.0
        task.wake_time = current_tick + duration
        task.sleep_count += 1

    def _wakeup_task(self, task_id: str):
        task = self.tasks[task_id]
        if task.state == "SLEEPING":
            if self.enable_sleeper_fairness:
                # CFS Sleeper Fairness: clamp vruntime so it doesn't get unbounded CPU monopoly
                thresh = self.sched_latency_ms / 2.0
                task.vruntime = max(task.vruntime, self.min_vruntime - thresh)
            task.state = "RUNNABLE"
            task.wake_time = None
            task.current_wait_time = 0.0

    def _summarize_results(self) -> Dict[str, Any]:
        task_stats = {}
        for tid, t in sorted(self.tasks.items()):
            task_stats[tid] = {
                "nice": t.nice,
                "weight": t.weight,
                "total_exec_time_ms": round(t.total_exec_time, 2),
                "final_vruntime": round(t.vruntime, 3),
                "max_wait_latency_ms": round(t.max_wait_latency_ms, 2)
            }
        
        max_wait = max((t.max_wait_latency_ms for t in self.tasks.values()), default=0.0)
        has_sleepers = any(t.sleep_count > 0 for t in self.tasks.values())

        if not self.enable_sleeper_fairness and max_wait >= 20.0:
            verdict = "CATASTROPHIC_SLEEPER_CPU_MONOPOLY"
        elif self.enable_sleeper_fairness and has_sleepers:
            verdict = "INTERACTIVE_SLEEPER_FAIR_RESPONSE"
        else:
            verdict = "COMPLETELY_FAIR_WEIGHTED_SHARING"

        return {
            "verdict": verdict,
            "min_vruntime": round(self.min_vruntime, 3),
            "max_wait_latency_ms": round(max_wait, 2),
            "tasks": task_stats
        }

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    req = json.loads(raw_data)
    sim = CfsSimulator(req["config"])
    result = sim.simulate(req["events"], req["total_ticks"])
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
