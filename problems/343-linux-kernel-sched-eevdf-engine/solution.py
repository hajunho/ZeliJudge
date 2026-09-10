import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NICE_TO_WEIGHT = {
    -20: 88761, -19: 71755, -18: 56483, -17: 46273, -16: 36291,
    -15: 29154, -14: 23254, -13: 18705, -12: 14949, -11: 11916,
    -10: 9548, -9: 7620, -8: 6100, -7: 4904, -6: 3906,
    -5: 3121, -4: 2501, -3: 1991, -2: 1586, -1: 1277,
    0: 1024,
    1: 820, 2: 655, 3: 526, 4: 423,
    5: 335, 6: 272, 7: 215, 8: 172, 9: 137,
    10: 110, 11: 87, 12: 70, 13: 56, 14: 45,
    15: 36, 16: 29, 17: 23, 18: 18, 19: 15
}

class Task:
    def __init__(self, task_id, nice, slice_ns):
        self.task_id = task_id
        self.nice = nice
        self.weight = NICE_TO_WEIGHT.get(nice, 1024)
        self.slice_ns = slice_ns
        self.vruntime = 0.0
        self.deadline = 0.0
        self.total_runtime_ns = 0
        self.state = "RUNNABLE"

class EEVDFEngine:
    def __init__(self, config):
        self.default_slice_ns = config.get("default_slice_ns", 3000000)
        self.current_time_ns = 0
        self.vruntime_avg = 0.0
        self.tasks = {}
        self.runnable_tasks = {}
        self.current_task_id = None
        self.current_task_slice_used = 0

    def _calc_total_weight(self):
        return sum(t.weight for t in self.runnable_tasks.values())

    def _update_deadline(self, task):
        task.deadline = task.vruntime + (task.slice_ns * 1024.0) / task.weight

    def add_task(self, op):
        tid = op["task_id"]
        nice = op.get("nice", 0)
        slice_ns = op.get("slice_ns", self.default_slice_ns)

        task = Task(tid, nice, slice_ns)
        task.vruntime = self.vruntime_avg
        self._update_deadline(task)
        self.tasks[tid] = task
        self.runnable_tasks[tid] = task

        return {
            "status": "TASK_ADDED",
            "task_id": tid,
            "weight": task.weight,
            "vruntime": round(task.vruntime, 2),
            "deadline": round(task.deadline, 2)
        }

    def pick_next(self):
        if not self.runnable_tasks:
            self.current_task_id = None
            return None

        eligible = [t for t in self.runnable_tasks.values() if t.vruntime <= self.vruntime_avg + 1e-9]
        if eligible:
            eligible.sort(key=lambda t: (t.deadline, t.vruntime, t.task_id))
            chosen = eligible[0]
        else:
            all_t = list(self.runnable_tasks.values())
            all_t.sort(key=lambda t: (t.vruntime, t.deadline, t.task_id))
            chosen = all_t[0]

        self.current_task_id = chosen.task_id
        chosen.state = "RUNNING"
        return chosen

    def run_step(self, op):
        delta_ns = op["delta_ns"]
        if not self.runnable_tasks:
            self.current_time_ns += delta_ns
            return {"status": "IDLE", "time_ns": self.current_time_ns}

        if self.current_task_id is None or self.current_task_id not in self.runnable_tasks:
            self.pick_next()
            self.current_task_slice_used = 0

        curr = self.runnable_tasks[self.current_task_id]
        total_w = self._calc_total_weight()

        curr.total_runtime_ns += delta_ns
        self.current_time_ns += delta_ns
        self.current_task_slice_used += delta_ns

        delta_v = (delta_ns * 1024.0) / curr.weight
        curr.vruntime += delta_v

        delta_V = (delta_ns * 1024.0) / total_w
        self.vruntime_avg += delta_V

        slice_expired = (self.current_task_slice_used >= curr.slice_ns)
        if slice_expired:
            self.current_task_slice_used = 0
            self._update_deadline(curr)
            old_tid = curr.task_id
            new_task = self.pick_next()
            context_switch = (new_task is not None and new_task.task_id != old_tid)
        else:
            candidate = self.pick_next()
            context_switch = (candidate is not None and candidate.task_id != curr.task_id)
            if context_switch:
                self.current_task_slice_used = 0

        return {
            "executed_task_id": curr.task_id,
            "runtime_added_ns": delta_ns,
            "task_vruntime": round(curr.vruntime, 2),
            "task_deadline": round(curr.deadline, 2),
            "global_vruntime": round(self.vruntime_avg, 2),
            "slice_expired": slice_expired,
            "current_task_id": self.current_task_id
        }

    def sleep_task(self, op):
        tid = op["task_id"]
        if tid in self.runnable_tasks:
            t = self.runnable_tasks.pop(tid)
            t.state = "SLEEPING"
            if self.current_task_id == tid:
                self.current_task_id = None
                self.current_task_slice_used = 0
            return {"status": "TASK_SLEPT", "task_id": tid}
        return {"error": "TASK_NOT_FOUND"}

    def wake_task(self, op):
        tid = op["task_id"]
        if tid in self.tasks and tid not in self.runnable_tasks:
            t = self.tasks[tid]
            t.vruntime = max(t.vruntime, self.vruntime_avg)
            self._update_deadline(t)
            t.state = "RUNNABLE"
            self.runnable_tasks[tid] = t
            return {
                "status": "TASK_WOKEN",
                "task_id": tid,
                "vruntime": round(t.vruntime, 2),
                "deadline": round(t.deadline, 2)
            }
        return {"error": "TASK_NOT_FOUND"}

    def get_stats(self):
        tasks_info = []
        for tid in sorted(self.tasks.keys()):
            t = self.tasks[tid]
            lag = self.vruntime_avg - t.vruntime
            tasks_info.append({
                "task_id": t.task_id,
                "nice": t.nice,
                "weight": t.weight,
                "slice_ns": t.slice_ns,
                "vruntime": round(t.vruntime, 2),
                "deadline": round(t.deadline, 2),
                "lag": round(lag, 2),
                "eligible": (t.vruntime <= self.vruntime_avg + 1e-9) if tid in self.runnable_tasks else False,
                "total_runtime_ns": t.total_runtime_ns,
                "state": t.state
            })
        return {
            "current_time_ns": self.current_time_ns,
            "global_vruntime": round(self.vruntime_avg, 2),
            "current_task_id": self.current_task_id,
            "runnable_count": len(self.runnable_tasks),
            "tasks": tasks_info
        }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = EEVDFEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "ADD_TASK":
            results.append(engine.add_task(op))
        elif name == "RUN_STEP":
            results.append(engine.run_step(op))
        elif name == "SLEEP_TASK":
            results.append(engine.sleep_task(op))
        elif name == "WAKE_TASK":
            results.append(engine.wake_task(op))
        elif name == "GET_STATS":
            results.append(engine.get_stats())
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
