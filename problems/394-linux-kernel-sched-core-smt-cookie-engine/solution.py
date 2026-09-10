# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #394 Solution:
Linux Kernel CPU Scheduling: Core Scheduling (PR_SCHED_CORE) SMT Cross-Hyperthread Speculative Side-Channel Mitigation & Cookie Matching Engine
"""
import sys
import json

# Windows UTF-8 encoding support
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class Task:
    def __init__(self, task_id, cookie, prio_type, prio_val, vruntime, burst, assigned_core, assigned_sibling=0):
        self.task_id = str(task_id)
        self.cookie = str(cookie)
        self.prio_type = str(prio_type).upper()
        self.prio_val = int(prio_val)
        self.vruntime = float(vruntime)
        self.burst_remaining = int(burst)
        self.burst_initial = int(burst)
        self.assigned_core = int(assigned_core)
        self.assigned_sibling = int(assigned_sibling)
        self.state = "RUNNABLE"
        self.total_exec = 0
        self.completion_time = None

def task_rank_tuple(task):
    if task.prio_type == "RT":
        return (0, -task.prio_val, 0.0, task.task_id)
    else:
        return (1, 0, task.vruntime, task.task_id)

def best_task(task_list):
    if not task_list:
        return None
    return min(task_list, key=task_rank_tuple)

class CoreSchedSimulator:
    def __init__(self, config):
        self.num_cores = int(config.get("num_cores", 1))
        self.siblings_per_core = int(config.get("siblings_per_core", 2))
        self.slice_duration = int(config.get("slice_duration", 10))
        self.current_time = 0
        self.tasks = {}
        self.rq = {c: {s: [] for s in range(self.siblings_per_core)} for c in range(self.num_cores)}
        self.stats = {
            c: {
                "active_exec_cycles": 0,
                "forced_idle_cycles": 0,
                "pure_idle_cycles": 0
            } for c in range(self.num_cores)
        }
        self.security_violations = 0
        self.completed_tasks = []
        self.audit_events = []

    def add_task(self, task_data):
        tid = str(task_data["task_id"])
        c = int(task_data["assigned_core"])
        s = int(task_data.get("assigned_sibling", 0))
        t = Task(
            task_id=tid,
            cookie=task_data.get("cookie", "0"),
            prio_type=task_data.get("prio_type", "CFS"),
            prio_val=task_data.get("prio_val", 0),
            vruntime=task_data.get("vruntime", 0.0),
            burst=task_data.get("burst", 10),
            assigned_core=c,
            assigned_sibling=s
        )
        self.tasks[tid] = t
        self.rq[c][s].append(tid)

    def process_event(self, ev):
        action = ev.get("action")
        if action == "PR_SCHED_CORE":
            op = ev.get("op")
            tid = str(ev.get("task_id", ev.get("source", "")))
            if op == "PR_SCHED_CORE_CREATE":
                new_c = str(ev.get("cookie", f"cookie_{tid}"))
                if tid in self.tasks:
                    self.tasks[tid].cookie = new_c
            elif op == "PR_SCHED_CORE_SHARE_TO":
                src = str(ev.get("source"))
                tgt = str(ev.get("target"))
                if src in self.tasks and tgt in self.tasks:
                    self.tasks[tgt].cookie = self.tasks[src].cookie
            elif op == "PR_SCHED_CORE_SHARE_FROM":
                src = str(ev.get("source"))
                tgt = str(ev.get("target", tid))
                if src in self.tasks and tgt in self.tasks:
                    self.tasks[tgt].cookie = self.tasks[src].cookie
            elif op == "PR_SCHED_CORE_RESET":
                if tid in self.tasks:
                    self.tasks[tid].cookie = "0"
        elif action == "ADD_TASK":
            self.add_task(ev["task"])

    def step_tick(self):
        all_done = True

        for c in range(self.num_cores):
            candidates = {}
            for s in range(self.siblings_per_core):
                runnables = [self.tasks[tid] for tid in self.rq[c][s] if self.tasks[tid].state == "RUNNABLE"]
                candidates[s] = best_task(runnables)

            if not any(candidates.values()):
                for s in range(self.siblings_per_core):
                    self.stats[c]["pure_idle_cycles"] += self.slice_duration
                continue

            all_done = False

            valid_cands = [t for t in candidates.values() if t is not None]
            leader_task = best_task(valid_cands)
            core_cookie = leader_task.cookie

            chosen_per_sib = {}
            audit_sib_states = {}
            for s in range(self.siblings_per_core):
                matching = [
                    self.tasks[tid] for tid in self.rq[c][s]
                    if self.tasks[tid].state == "RUNNABLE" and self.tasks[tid].cookie == core_cookie
                ]
                if matching:
                    chosen = best_task(matching)
                    chosen_per_sib[s] = ("RUNNING", chosen)
                    audit_sib_states[f"sibling_{s}"] = chosen.task_id
                else:
                    has_any = any(self.tasks[tid].state == "RUNNABLE" for tid in self.rq[c][s])
                    if has_any:
                        chosen_per_sib[s] = ("FORCED_IDLE", None)
                        audit_sib_states[f"sibling_{s}"] = "FORCED_IDLE"
                    else:
                        chosen_per_sib[s] = ("PURE_IDLE", None)
                        audit_sib_states[f"sibling_{s}"] = "PURE_IDLE"

            active_cookies = set()
            for s, (state, task) in chosen_per_sib.items():
                if state == "RUNNING":
                    active_cookies.add(task.cookie)
            if len(active_cookies) > 1:
                self.security_violations += 1

            self.audit_events.append({
                "timestamp": self.current_time,
                "core_id": c,
                "cookie": core_cookie,
                **audit_sib_states
            })

            for s, (state, task) in chosen_per_sib.items():
                if state == "RUNNING":
                    exec_dur = min(self.slice_duration, task.burst_remaining)
                    task.burst_remaining -= exec_dur
                    task.total_exec += exec_dur
                    if task.prio_type == "CFS":
                        task.vruntime += float(exec_dur)
                    self.stats[c]["active_exec_cycles"] += exec_dur
                    if exec_dur < self.slice_duration:
                        self.stats[c]["pure_idle_cycles"] += (self.slice_duration - exec_dur)
                    if task.burst_remaining <= 0:
                        task.state = "COMPLETED"
                        task.completion_time = self.current_time + exec_dur
                        self.rq[c][s].remove(task.task_id)
                        self.completed_tasks.append(task.task_id)
                elif state == "FORCED_IDLE":
                    self.stats[c]["forced_idle_cycles"] += self.slice_duration
                else:
                    self.stats[c]["pure_idle_cycles"] += self.slice_duration

        self.current_time += self.slice_duration
        return not all_done

    def run(self, events=None, max_ticks=100):
        if events is None:
            events = []
        events = sorted(events, key=lambda x: x.get("at_time", 0))
        ev_idx = 0
        ticks_done = 0

        for _ in range(max_ticks):
            while ev_idx < len(events) and events[ev_idx].get("at_time", 0) <= self.current_time:
                self.process_event(events[ev_idx])
                ev_idx += 1

            has_work = self.step_tick()
            ticks_done += 1

            all_completed = len(self.tasks) > 0 and all(t.state == "COMPLETED" for t in self.tasks.values())
            if all_completed and ev_idx >= len(events):
                break

        total_active = sum(self.stats[c]["active_exec_cycles"] for c in range(self.num_cores))
        total_forced = sum(self.stats[c]["forced_idle_cycles"] for c in range(self.num_cores))
        total_pure = sum(self.stats[c]["pure_idle_cycles"] for c in range(self.num_cores))
        total_cap = total_active + total_forced + total_pure
        forced_idle_ratio = round(total_forced / total_cap, 4) if total_cap > 0 else 0.0

        task_log = {}
        for tid in sorted(self.tasks.keys()):
            t = self.tasks[tid]
            task_log[tid] = {
                "burst_initial": t.burst_initial,
                "burst_remaining": t.burst_remaining,
                "total_exec": t.total_exec,
                "completion_time": t.completion_time,
                "final_cookie": t.cookie,
                "final_vruntime": round(t.vruntime, 2),
                "state": t.state
            }

        core_stats_out = {str(c): self.stats[c] for c in range(self.num_cores)}

        return {
            "total_time": self.current_time,
            "ticks_executed": ticks_done,
            "security_violations": self.security_violations,
            "isolation_guaranteed": (self.security_violations == 0),
            "completed_tasks": self.completed_tasks,
            "forced_idle_ratio": forced_idle_ratio,
            "core_stats": core_stats_out,
            "task_log": task_log,
            "audit_events": self.audit_events
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    sim = CoreSchedSimulator(config)
    for t_data in data.get("tasks", []):
        sim.add_task(t_data)
    events = data.get("events", [])
    max_ticks = data.get("max_ticks", 100)
    result = sim.run(events, max_ticks)
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
