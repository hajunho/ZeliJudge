import sys
import os
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class LinuxSchedDeadlineEngine:
    def __init__(self, config: dict):
        self.config = copy.deepcopy(config)
        self.max_bandwidth = float(self.config.get("max_bandwidth", 0.95))
        self.current_time = float(self.config.get("initial_time_ms", 0.0))

        self.tasks = {}
        self.total_bandwidth = 0.0
        self.running_task = None
        self.event_log = []
        self.history = []

        self.stats = {
            "admitted_tasks": 0,
            "rejected_tasks": 0,
            "context_switches": 0,
            "throttling_events": 0,
            "replenish_events": 0,
            "deadline_misses": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def register_task(self, task_id: str, runtime_ms: float, deadline_ms: float, period_ms: float) -> dict:
        utilization = round(runtime_ms / period_ms, 4)
        if round(self.total_bandwidth + utilization, 4) > self.max_bandwidth:
            self.stats["rejected_tasks"] += 1
            self.log(f"ADMISSION_REJECTED: task={task_id} util={utilization} total_bw={round(self.total_bandwidth, 4)} > max_bw={self.max_bandwidth}")
            res = {
                "op": "REGISTER_TASK",
                "task_id": task_id,
                "status": "REJECTED",
                "error": "-EBUSY",
                "requested_utilization": utilization,
                "total_bandwidth": round(self.total_bandwidth, 4)
            }
            self.history.append(res)
            return res

        self.total_bandwidth = round(self.total_bandwidth + utilization, 4)
        self.stats["admitted_tasks"] += 1
        t_info = {
            "task_id": task_id,
            "runtime_ms": runtime_ms,
            "deadline_ms": deadline_ms,
            "period_ms": period_ms,
            "utilization": utilization,
            "budget": runtime_ms,
            "abs_deadline": round(self.current_time + deadline_ms, 4),
            "status": "READY"
        }
        self.tasks[task_id] = t_info
        self.log(f"TASK_ADMITTED: task={task_id} Q={runtime_ms}ms D={deadline_ms}ms P={period_ms}ms util={utilization}")
        res = {
            "op": "REGISTER_TASK",
            "task_id": task_id,
            "status": "ADMITTED",
            "utilization": utilization,
            "total_bandwidth": round(self.total_bandwidth, 4),
            "abs_deadline": t_info["abs_deadline"],
            "budget": t_info["budget"]
        }
        self.history.append(res)
        return res

    def _unthrottle_tasks(self):
        for tid, t in self.tasks.items():
            if t["status"] == "THROTTLED" and self.current_time >= t["abs_deadline"]:
                t["budget"] = t["runtime_ms"]
                t["abs_deadline"] = round(t["abs_deadline"] + t["period_ms"], 4)
                t["status"] = "READY"
                self.stats["replenish_events"] += 1
                self.log(f"TASK_UNTHROTTLED: task={tid} budget_replenished={t['budget']} new_dl={t['abs_deadline']}")

    def _pick_next_task(self) -> str:
        best_tid = None
        best_dl = float("inf")
        for tid, t in self.tasks.items():
            if t["status"] in ("READY", "RUNNING") and t["budget"] > 0:
                if t["abs_deadline"] < best_dl:
                    best_dl = t["abs_deadline"]
                    best_tid = tid
        return best_tid

    def step_time(self, duration_ms: float) -> dict:
        step_end = round(self.current_time + duration_ms, 4)

        while self.current_time < step_end:
            self._unthrottle_tasks()

            next_task = self._pick_next_task()
            if next_task != self.running_task:
                if self.running_task and self.tasks[self.running_task]["status"] == "RUNNING":
                    self.tasks[self.running_task]["status"] = "READY"
                if next_task:
                    self.tasks[next_task]["status"] = "RUNNING"
                    self.stats["context_switches"] += 1
                self.running_task = next_task

            next_event_time = step_end
            if self.running_task:
                t_run = self.tasks[self.running_task]
                budget_exhaust_time = round(self.current_time + t_run["budget"], 4)
                if budget_exhaust_time < next_event_time:
                    next_event_time = budget_exhaust_time

            for tid, t in self.tasks.items():
                if t["status"] == "THROTTLED" and t["abs_deadline"] > self.current_time:
                    if t["abs_deadline"] < next_event_time:
                        next_event_time = t["abs_deadline"]

            delta = round(next_event_time - self.current_time, 4)
            if delta <= 0:
                delta = 0.0001

            if self.running_task:
                t_run = self.tasks[self.running_task]
                t_run["budget"] = round(max(0.0, t_run["budget"] - delta), 4)

                if round(self.current_time + delta, 4) > t_run["abs_deadline"] and t_run["budget"] > 0:
                    self.stats["deadline_misses"] += 1
                    self.log(f"DEADLINE_MISS: task={self.running_task} dl={t_run['abs_deadline']} time={round(self.current_time + delta, 4)}")

                if t_run["budget"] <= 0:
                    t_run["status"] = "THROTTLED"
                    self.stats["throttling_events"] += 1
                    self.log(f"TASK_THROTTLED: task={self.running_task} budget exhausted at time={round(self.current_time + delta, 4)}")
                    self.running_task = None

            self.current_time = round(self.current_time + delta, 4)
            self._unthrottle_tasks()

        res = {
            "op": "STEP_TIME",
            "current_time": self.current_time,
            "running_task": self.running_task,
            "ready_tasks": [tid for tid, t in self.tasks.items() if t["status"] in ("READY", "RUNNING")],
            "throttled_tasks": [tid for tid, t in self.tasks.items() if t["status"] == "THROTTLED"]
        }
        self.history.append(res)
        return res

    def task_sleep(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            return {"op": "TASK_SLEEP", "error": "TASK_NOT_FOUND"}
        t = self.tasks[task_id]
        if self.running_task == task_id:
            self.running_task = None
        t["status"] = "SLEEPING"
        self.log(f"TASK_SLEEP: task={task_id} budget={t['budget']} dl={t['abs_deadline']}")
        res = {
            "op": "TASK_SLEEP",
            "task_id": task_id,
            "status": "SLEEPING",
            "remaining_budget": t["budget"],
            "abs_deadline": t["abs_deadline"]
        }
        self.history.append(res)
        return res

    def task_wakeup(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            return {"op": "TASK_WAKEUP", "error": "TASK_NOT_FOUND"}
        t = self.tasks[task_id]

        check_time = self.current_time + (t["budget"] / t["runtime_ms"]) * t["deadline_ms"]
        if check_time < t["abs_deadline"]:
            cbs_rule = "PRESERVED"
        else:
            t["budget"] = t["runtime_ms"]
            t["abs_deadline"] = round(self.current_time + t["deadline_ms"], 4)
            cbs_rule = "REPLENISHED"
            self.stats["replenish_events"] += 1

        t["status"] = "READY"
        self.log(f"TASK_WAKEUP: task={task_id} rule={cbs_rule} budget={t['budget']} dl={t['abs_deadline']}")
        res = {
            "op": "TASK_WAKEUP",
            "task_id": task_id,
            "cbs_rule": cbs_rule,
            "status": "READY",
            "budget": t["budget"],
            "abs_deadline": t["abs_deadline"]
        }
        self.history.append(res)
        return res

    def get_state(self) -> dict:
        task_snapshots = {}
        for tid, t in self.tasks.items():
            task_snapshots[tid] = {
                "status": t["status"],
                "budget": t["budget"],
                "abs_deadline": t["abs_deadline"],
                "utilization": t["utilization"]
            }
        return {
            "op": "GET_STATE",
            "current_time": self.current_time,
            "running_task": self.running_task,
            "total_bandwidth": round(self.total_bandwidth, 4),
            "tasks": task_snapshots
        }

    def get_final_summary(self) -> dict:
        task_snapshots = {}
        for tid, t in self.tasks.items():
            task_snapshots[tid] = {
                "status": t["status"],
                "budget": t["budget"],
                "abs_deadline": t["abs_deadline"],
                "utilization": t["utilization"]
            }
        return {
            "current_time": self.current_time,
            "running_task": self.running_task,
            "total_bandwidth": round(self.total_bandwidth, 4),
            "tasks": task_snapshots,
            "stats": self.stats,
            "event_count": len(self.event_log)
        }

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    eng = LinuxSchedDeadlineEngine(data["config"])
    results = []
    for op in data.get("operations", []):
        cmd = op["op"]
        if cmd == "REGISTER_TASK":
            res = eng.register_task(
                task_id=op["task_id"],
                runtime_ms=float(op["runtime_ms"]),
                deadline_ms=float(op["deadline_ms"]),
                period_ms=float(op["period_ms"])
            )
            results.append(res)
        elif cmd == "STEP_TIME":
            res = eng.step_time(duration_ms=float(op["duration_ms"]))
            results.append(res)
        elif cmd == "TASK_SLEEP":
            res = eng.task_sleep(task_id=op["task_id"])
            results.append(res)
        elif cmd == "TASK_WAKEUP":
            res = eng.task_wakeup(task_id=op["task_id"])
            results.append(res)
        elif cmd == "GET_STATE":
            res = eng.get_state()
            results.append(res)

    output = {
        "results": results,
        "final_summary": eng.get_final_summary()
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
