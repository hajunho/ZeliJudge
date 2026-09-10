import sys
import os
import json

class MemcgNode:
    def __init__(self, name: str, parent=None, config=None):
        self.name = name
        self.parent = parent
        self.children = {}
        config = config or {}
        self.memory_min = config.get("memory_min", 0)
        self.memory_low = config.get("memory_low", 0)
        self.memory_high = config.get("memory_high", float("inf"))
        self.memory_max = config.get("memory_max", float("inf"))
        self.usage = 0
        self.rss_anon = 0
        self.rss_file = 0
        self.tasks = {}
        self.oom_events = 0
        self.throttle_events = 0
        self.reclaim_events = 0

    def charge(self, amount: int, is_anon: bool = True):
        self.usage += amount
        if is_anon:
            self.rss_anon += amount
        else:
            self.rss_file += amount
        if self.parent:
            self.parent.charge(amount, is_anon)

    def uncharge(self, amount: int, is_anon: bool = True):
        self.usage = max(0, self.usage - amount)
        if is_anon:
            self.rss_anon = max(0, self.rss_anon - amount)
        else:
            self.rss_file = max(0, self.rss_file - amount)
        if self.parent:
            self.parent.uncharge(amount, is_anon)

class OOMKillerEngine:
    def __init__(self, config):
        self.total_memory = config.get("total_memory", 16384)
        self.root = MemcgNode("root")
        self.cgroups = {"root": self.root}
        self.tasks = {}
        self.event_log = []
        self.history = []
        self.stats = {
            "allocations": 0,
            "throttles": 0,
            "reclaims": 0,
            "reclaimed_pages": 0,
            "oom_kills": 0,
            "pages_reaped": 0
        }

        for cg in config.get("cgroups", []):
            self.create_cgroup(cg["path"], cg.get("parent", "root"), cg)

    def log(self, msg: str):
        self.event_log.append(msg)

    def create_cgroup(self, path: str, parent_path: str = "root", config: dict = None):
        parent = self.cgroups.get(parent_path, self.root)
        node = MemcgNode(path, parent, config)
        parent.children[path] = node
        self.cgroups[path] = node
        self.log(f"CGROUP_CREATE path={path} parent={parent_path}")

    def add_task(self, pid: int, cgroup_path: str, oom_score_adj: int = 0):
        cg = self.cgroups.get(cgroup_path, self.root)
        task = {
            "pid": pid,
            "cgroup": cgroup_path,
            "rss_anon": 0,
            "rss_file": 0,
            "swap": 0,
            "oom_score_adj": oom_score_adj,
            "alive": True
        }
        self.tasks[pid] = task
        cg.tasks[pid] = task
        self.log(f"TASK_ADD pid={pid} cgroup={cgroup_path} adj={oom_score_adj}")

    def calc_badness(self, task: dict) -> int:
        if task["oom_score_adj"] <= -1000:
            return 0
        points = task["rss_anon"] + task["rss_file"] + task["swap"]
        adj = (task["oom_score_adj"] * self.total_memory) / 1000.0
        return max(1, int(points + adj))

    def direct_reclaim(self, cg: MemcgNode, target_amount: int) -> int:
        reclaimed = 0
        def scan_reclaim(node: MemcgNode):
            nonlocal reclaimed
            for t in node.tasks.values():
                if t["alive"] and t["rss_file"] > 0:
                    avail = t["rss_file"]
                    freed = min(avail, target_amount - reclaimed)
                    t["rss_file"] -= freed
                    node.uncharge(freed, is_anon=False)
                    reclaimed += freed
                    if reclaimed >= target_amount:
                        return
            for child in node.children.values():
                if reclaimed >= target_amount:
                    break
                scan_reclaim(child)

        scan_reclaim(cg)
        if reclaimed > 0:
            cg.reclaim_events += 1
            self.stats["reclaims"] += 1
            self.stats["reclaimed_pages"] += reclaimed
            self.log(f"DIRECT_RECLAIM in {cg.name} freed={reclaimed}")
        return reclaimed

    def allocate_memory(self, pid: int, amount: int, is_anon: bool = True) -> dict:
        if pid not in self.tasks or not self.tasks[pid]["alive"]:
            res = {"op": "ALLOC", "pid": pid, "status": "TASK_DEAD"}
            self.history.append(res)
            return res

        task = self.tasks[pid]
        cg = self.cgroups[task["cgroup"]]
        self.stats["allocations"] += 1

        if cg.usage + amount > cg.memory_high:
            cg.throttle_events += 1
            self.stats["throttles"] += 1
            excess = (cg.usage + amount) - cg.memory_high
            self.log(f"MEMCG_HIGH_THROTTLE pid={pid} cgroup={cg.name} excess={excess}")

        if cg.usage + amount > cg.memory_max:
            needed = (cg.usage + amount) - cg.memory_max
            freed = self.direct_reclaim(cg, needed)
            if cg.usage + amount > cg.memory_max:
                self.log(f"MEMCG_MAX_EXCEEDED pid={pid} cgroup={cg.name} usage={cg.usage+amount} max={cg.memory_max}")
                kill_res = self.trigger_oom(cg)
                if not kill_res["killed"]:
                    res = {"op": "ALLOC", "pid": pid, "status": "OOM_ENOMEM"}
                    self.history.append(res)
                    return res

        cg.charge(amount, is_anon=is_anon)
        if is_anon:
            task["rss_anon"] += amount
        else:
            task["rss_file"] += amount

        res = {"op": "ALLOC", "pid": pid, "status": "SUCCESS", "allocated": amount, "cg_usage": cg.usage}
        self.history.append(res)
        return res

    def free_memory(self, pid: int, amount: int, is_anon: bool = True) -> dict:
        if pid not in self.tasks or not self.tasks[pid]["alive"]:
            res = {"op": "FREE", "pid": pid, "status": "TASK_DEAD"}
            self.history.append(res)
            return res

        task = self.tasks[pid]
        cg = self.cgroups[task["cgroup"]]
        if is_anon:
            freed = min(task["rss_anon"], amount)
            task["rss_anon"] -= freed
        else:
            freed = min(task["rss_file"], amount)
            task["rss_file"] -= freed

        cg.uncharge(freed, is_anon=is_anon)
        self.log(f"FREE_MEMORY pid={pid} freed={freed} cg_usage={cg.usage}")
        res = {"op": "FREE", "pid": pid, "status": "SUCCESS", "freed": freed, "cg_usage": cg.usage}
        self.history.append(res)
        return res

    def trigger_oom(self, target_cg: MemcgNode) -> dict:
        candidates = []
        def collect_tasks(node: MemcgNode):
            for t in node.tasks.values():
                if t["alive"]:
                    badness = self.calc_badness(t)
                    if badness > 0:
                        candidates.append((badness, t["rss_anon"], -t["pid"], t))
            for child in node.children.values():
                collect_tasks(child)

        collect_tasks(target_cg)
        if not candidates:
            self.log(f"OOM_KILLER_INVOKED in {target_cg.name} NO_ELIGIBLE_VICTIMS")
            return {"killed": False, "victim": None}

        candidates.sort(reverse=True)
        victim_tuple = candidates[0]
        victim = victim_tuple[3]
        v_badness = victim_tuple[0]

        victim["alive"] = False
        reaped_anon = victim["rss_anon"]
        reaped_file = victim["rss_file"]
        reaped_total = reaped_anon + reaped_file + victim["swap"]

        victim_cg = self.cgroups[victim["cgroup"]]
        victim_cg.uncharge(reaped_anon, is_anon=True)
        victim_cg.uncharge(reaped_file, is_anon=False)

        self.stats["oom_kills"] += 1
        self.stats["pages_reaped"] += reaped_total
        target_cg.oom_events += 1

        self.log(f"OOM_KILL_VICTIM pid={victim['pid']} badness={v_badness} reaped={reaped_total} cgroup={victim['cgroup']}")
        return {
            "killed": True,
            "victim_pid": victim["pid"],
            "badness": v_badness,
            "reaped_memory": reaped_total,
            "cgroup": victim["cgroup"]
        }

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = OOMKillerEngine(config)

    for op_info in operations:
        op = op_info.get("op")
        if op == "ADD_TASK":
            pid = op_info.get("pid")
            cgroup = op_info.get("cgroup", "root")
            adj = op_info.get("oom_score_adj", 0)
            engine.add_task(pid, cgroup, adj)
        elif op == "ALLOC":
            pid = op_info.get("pid")
            amount = op_info.get("amount", 0)
            is_anon = op_info.get("is_anon", True)
            engine.allocate_memory(pid, amount, is_anon)
        elif op == "FREE":
            pid = op_info.get("pid")
            amount = op_info.get("amount", 0)
            is_anon = op_info.get("is_anon", True)
            engine.free_memory(pid, amount, is_anon)
        elif op == "SET_OOM_SCORE_ADJ":
            pid = op_info.get("pid")
            adj = op_info.get("oom_score_adj", 0)
            if pid in engine.tasks:
                engine.tasks[pid]["oom_score_adj"] = adj

    cgroups_dump = {}
    for path in sorted(engine.cgroups.keys()):
        cg = engine.cgroups[path]
        cgroups_dump[path] = {
            "usage": cg.usage,
            "rss_anon": cg.rss_anon,
            "rss_file": cg.rss_file,
            "oom_events": cg.oom_events,
            "throttle_events": cg.throttle_events,
            "reclaim_events": cg.reclaim_events
        }

    tasks_dump = {}
    for pid in sorted(engine.tasks.keys()):
        t = engine.tasks[pid]
        tasks_dump[str(pid)] = {
            "alive": t["alive"],
            "cgroup": t["cgroup"],
            "rss_anon": t["rss_anon"],
            "rss_file": t["rss_file"],
            "oom_score_adj": t["oom_score_adj"],
            "badness": engine.calc_badness(t)
        }

    return {
        "stats": engine.stats,
        "cgroups": cgroups_dump,
        "tasks": tasks_dump,
        "history": engine.history,
        "event_log": engine.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
