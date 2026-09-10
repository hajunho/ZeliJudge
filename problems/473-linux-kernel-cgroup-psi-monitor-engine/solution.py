import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class PsiEngine:
    def __init__(self, config=None):
        self.config = config or {}
        self.current_time_us = 0
        self.cgroups = {"root": {"parent": None, "children": []}}
        self.tasks = {}
        self.triggers = {}
        self.events = []
        self.history = {"root": []}
        self.stats = {
            "total_trigger_firings": 0,
            "total_state_transitions": 0,
            "total_time_advanced_us": 0,
            "oom_actions": 0
        }

    def create_cgroup(self, name, parent="root"):
        if name not in self.cgroups:
            self.cgroups[name] = {"parent": parent, "children": []}
            if parent in self.cgroups:
                self.cgroups[parent]["children"].append(name)
            self.history[name] = []

    def register_trigger(self, trigger_id, cgroup, resource, stall_type, threshold_us, window_us, cooldown_us=None):
        if cooldown_us is None:
            cooldown_us = window_us
        self.triggers[trigger_id] = {
            "trigger_id": trigger_id,
            "cgroup": cgroup,
            "resource": resource,
            "stall_type": stall_type,
            "threshold_us": threshold_us,
            "window_us": window_us,
            "cooldown_us": cooldown_us,
            "last_fired_us": -10**9,
            "firing_count": 0
        }

    def set_task_state(self, task_id, cgroup, state):
        self.tasks[task_id] = {"cgroup": cgroup, "state": state}
        self.stats["total_state_transitions"] += 1

    def _get_cgroup_tasks(self, cg_name):
        res = []
        for tid, tinfo in self.tasks.items():
            if tinfo["state"] in ("SLEEPING", "TERMINATED"):
                continue
            curr = tinfo["cgroup"]
            while curr:
                if curr == cg_name:
                    res.append(tinfo)
                    break
                curr = self.cgroups.get(curr, {}).get("parent")
        return res

    def _evaluate_instant_stall(self, cg_name):
        tasks = self._get_cgroup_tasks(cg_name)
        n = len(tasks)
        stalls = {
            "memory": {"some": False, "full": False},
            "io": {"some": False, "full": False},
            "cpu": {"some": False, "full": False}
        }
        if n == 0:
            return stalls

        mem_count = sum(1 for t in tasks if t["state"] == "MEMSTALL")
        stalls["memory"]["some"] = (mem_count > 0)
        stalls["memory"]["full"] = (mem_count == n)

        io_count = sum(1 for t in tasks if t["state"] == "IOWAIT")
        stalls["io"]["some"] = (io_count > 0)
        stalls["io"]["full"] = (io_count == n)

        cpu_count = sum(1 for t in tasks if t["state"] == "CPU_QUEUED")
        stalls["cpu"]["some"] = (cpu_count > 0)
        stalls["cpu"]["full"] = False

        return stalls

    def advance_time(self, delta_us):
        t_start = self.current_time_us
        t_end = t_start + delta_us
        self.current_time_us = t_end
        self.stats["total_time_advanced_us"] += delta_us

        for cg in self.cgroups:
            stalls = self._evaluate_instant_stall(cg)
            self.history[cg].append({
                "t_start": t_start,
                "t_end": t_end,
                "duration": delta_us,
                "stalls": stalls
            })

        fired_in_step = []
        for tid, tr in self.triggers.items():
            cg = tr["cgroup"]
            res = tr["resource"]
            stype = tr["stall_type"]
            win = tr["window_us"]
            thresh = tr["threshold_us"]

            win_start = t_end - win
            accum_stall = 0
            for slice_item in reversed(self.history.get(cg, [])):
                if slice_item["t_end"] <= win_start:
                    break
                overlap_start = max(slice_item["t_start"], win_start)
                overlap_end = slice_item["t_end"]
                overlap_dur = max(0, overlap_end - overlap_start)
                if slice_item["stalls"][res][stype]:
                    accum_stall += overlap_dur

            if accum_stall >= thresh:
                if (t_end - tr["last_fired_us"]) >= tr["cooldown_us"]:
                    tr["last_fired_us"] = t_end
                    tr["firing_count"] += 1
                    self.stats["total_trigger_firings"] += 1
                    event = {
                        "trigger_id": tid,
                        "cgroup": cg,
                        "resource": res,
                        "stall_type": stype,
                        "timestamp_us": t_end,
                        "window_stall_us": accum_stall,
                        "threshold_us": thresh,
                        "window_us": win
                    }
                    self.events.append(event)
                    fired_in_step.append(event)

        return fired_in_step

    def query_psi(self, cgroup, resource):
        hist = self.history.get(cgroup, [])
        total_some = sum(s["duration"] for s in hist if s["stalls"][resource]["some"])
        total_full = sum(s["duration"] for s in hist if s["stalls"][resource]["full"])
        curr_stalls = self._evaluate_instant_stall(cgroup)[resource]
        return {
            "cgroup": cgroup,
            "resource": resource,
            "total_some_us": total_some,
            "total_full_us": total_full,
            "current_stall": curr_stalls
        }

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op["type"]
            if t == "CREATE_CGROUP":
                self.create_cgroup(op["name"], op.get("parent", "root"))
                results.append({
                    "op_index": idx,
                    "type": t,
                    "name": op["name"],
                    "parent": op.get("parent", "root"),
                    "status": "CREATED"
                })
            elif t == "REGISTER_TRIGGER":
                self.register_trigger(
                    op["trigger_id"],
                    op["cgroup"],
                    op["resource"],
                    op["stall_type"],
                    op["threshold_us"],
                    op["window_us"],
                    op.get("cooldown_us")
                )
                results.append({
                    "op_index": idx,
                    "type": t,
                    "trigger_id": op["trigger_id"],
                    "cgroup": op["cgroup"],
                    "status": "REGISTERED"
                })
            elif t == "TASK_STATE_TRANSITION":
                self.set_task_state(op["task_id"], op["cgroup"], op["state"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "task_id": op["task_id"],
                    "cgroup": op["cgroup"],
                    "state": op["state"]
                })
            elif t == "ADVANCE_TIME":
                fired = self.advance_time(op["delta_us"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "delta_us": op["delta_us"],
                    "current_time_us": self.current_time_us,
                    "triggers_fired": fired
                })
            elif t == "QUERY_PSI":
                res = self.query_psi(op["cgroup"], op["resource"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    **res
                })
            elif t == "OOM_KILL_ACTION":
                tid = op["task_id"]
                if tid in self.tasks:
                    self.tasks[tid]["state"] = "TERMINATED"
                    self.stats["oom_actions"] += 1
                results.append({
                    "op_index": idx,
                    "type": t,
                    "killed_task": tid,
                    "status": "TERMINATED"
                })

        return {
            "operation_results": results,
            "trigger_events": self.events,
            "summary": {
                "total_operations": len(ops),
                "total_time_us": self.current_time_us,
                "stats": self.stats
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    engine = PsiEngine(data.get("config", {}))
    output = engine.run(data.get("operations", []))
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
