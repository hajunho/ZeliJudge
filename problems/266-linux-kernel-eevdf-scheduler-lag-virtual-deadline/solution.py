import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

NICE_TO_WEIGHT = {
    -20: 88761, -19: 71755, -18: 56483, -17: 46273, -16: 36291,
    -15: 29154, -14: 23254, -13: 18705, -12: 14949, -11: 11916,
    -10: 9548,  -9: 7620,   -8: 6100,   -7: 4904,   -6: 3906,
    -5: 3121,   -4: 2501,   -3: 1991,   -2: 1586,   -1: 1277,
     0: 1024,    1: 820,     2: 655,     3: 526,     4: 423,
     5: 335,     6: 272,     7: 215,     8: 172,     9: 137,
    10: 110,    11: 87,     12: 70,     13: 56,     14: 45,
    15: 36,     16: 29,     17: 23,     18: 18,     19: 15
}

class EEVDFTask:
    def __init__(self, spec):
        self.task_id = spec["id"]
        self.nice = spec.get("nice", 0)
        self.weight = NICE_TO_WEIGHT.get(self.nice, 1024)
        self.slice_ms = float(spec.get("slice_ms", 4.0))
        self.total_work_ms = float(spec.get("total_work_ms", 1000.0))
        self.arrival_time_ms = float(spec.get("arrival_time_ms", 0.0))
        self.sleep_intervals = sorted(spec.get("sleep_intervals", []), key=lambda x: x["start_ms"])

        self.vruntime = 0.0
        self.runtime_ms = 0.0
        self.deadline = 0.0
        self.lag = 0.0
        self.state = "WAITING_ARRIVAL" if self.arrival_time_ms > 0 else "RUNNABLE"
        self.context_switches = 0
        self.preemptions_caused = 0

    def compute_deadline(self):
        self.deadline = self.vruntime + (self.slice_ms * 1024.0 / self.weight)

    def is_eligible(self, V):
        return self.vruntime <= V + 1e-9

def run_eevdf_simulation(data):
    config = data.get("config", {})
    total_duration_ms = float(config.get("total_duration_ms", 50.0))
    tick_ms = float(config.get("tick_ms", 0.5))
    decay_tau_ms = float(config.get("lag_decay_tau_ms", 10.0))
    tasks_spec = data.get("tasks", [])

    tasks = {ts["id"]: EEVDFTask(ts) for ts in tasks_spec}

    V = 0.0
    time = 0.0
    current_task = None
    timeline = []

    for t in tasks.values():
        if t.arrival_time_ms == 0:
            t.vruntime = V
            t.compute_deadline()

    while time < total_duration_ms - 1e-9:
        for t in tasks.values():
            if t.state == "WAITING_ARRIVAL" and time >= t.arrival_time_ms - 1e-9:
                t.state = "RUNNABLE"
                t.vruntime = V
                t.compute_deadline()

        for t in tasks.values():
            if t.state in ("RUNNABLE", "RUNNING"):
                for s in t.sleep_intervals:
                    if s["start_ms"] <= time < s["end_ms"]:
                        t.state = "SLEEPING"
                        t.sleep_until = s["end_ms"]
                        t.last_sleep_start = time
                        if current_task == t:
                            current_task = None
                        break
            elif t.state == "SLEEPING":
                if time >= t.sleep_until - 1e-9:
                    t.state = "RUNNABLE"
                    initial_lag = V - t.vruntime
                    if decay_tau_ms > 0 and hasattr(t, "last_sleep_start"):
                        delta_s = time - t.last_sleep_start
                        decayed_lag = initial_lag * math.exp(-delta_s / decay_tau_ms)
                    else:
                        decayed_lag = initial_lag
                    decayed_lag = max(-t.slice_ms, min(t.slice_ms * 2.0, decayed_lag))
                    t.vruntime = V - decayed_lag
                    t.compute_deadline()

        runnable = [t for t in tasks.values() if t.state in ("RUNNABLE", "RUNNING") and t.runtime_ms < t.total_work_ms - 1e-9]

        if not runnable:
            time += tick_ms
            continue

        total_weight = sum(t.weight for t in runnable)

        eligible = [t for t in runnable if t.is_eligible(V)]
        if not eligible:
            V = min(t.vruntime for t in runnable)
            eligible = [t for t in runnable if t.is_eligible(V)]

        best_task = min(eligible, key=lambda t: (t.deadline, t.task_id))

        if current_task != best_task:
            if current_task is not None and current_task.state == "RUNNING":
                current_task.state = "RUNNABLE"
            best_task.context_switches += 1
            if current_task is not None:
                best_task.preemptions_caused += 1
            current_task = best_task
            current_task.state = "RUNNING"

        dt = min(tick_ms, current_task.total_work_ms - current_task.runtime_ms)
        current_task.runtime_ms += dt

        dv = dt * 1024.0 / current_task.weight
        current_task.vruntime += dv
        current_task.compute_deadline()

        V += dt * 1024.0 / total_weight

        if current_task.runtime_ms >= current_task.total_work_ms - 1e-9:
            current_task.state = "FINISHED"
            current_task = None

        time += dt
        for t in runnable:
            t.lag = V - t.vruntime

        timeline.append({
            "time_ms": round(time, 2),
            "running_task": current_task.task_id if current_task else "IDLE",
            "virtual_time": round(V, 4),
            "runnable_count": len(runnable)
        })

    task_reports = []
    for t in sorted(tasks.values(), key=lambda x: x.task_id):
        task_reports.append({
            "task_id": t.task_id,
            "nice": t.nice,
            "weight": t.weight,
            "slice_ms": t.slice_ms,
            "runtime_ms": round(t.runtime_ms, 2),
            "cpu_share_percent": round((t.runtime_ms / time) * 100.0, 2) if time > 0 else 0.0,
            "vruntime": round(t.vruntime, 4),
            "deadline": round(t.deadline, 4),
            "final_lag": round(V - t.vruntime, 4),
            "context_switches": t.context_switches,
            "preemptions_caused": t.preemptions_caused,
            "state": t.state
        })

    return {
        "simulation_summary": {
            "total_duration_ms": round(time, 2),
            "final_virtual_time": round(V, 4),
            "total_tasks": len(tasks),
            "completed_tasks": sum(1 for t in tasks.values() if t.state == "FINISHED")
        },
        "tasks": task_reports,
        "timeline_sample": timeline[:10]
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    res = run_eevdf_simulation(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
