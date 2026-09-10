# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #341: Linux Kernel Cgroup v2 Hierarchical Memory Controller & OOM Engine.
"""
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

class MemCgroupV2Engine:
    def __init__(self, config=None):
        self.cgroups = {
            "/": {
                "path": "/",
                "parent": None,
                "children": set(),
                "min": 0,
                "low": 0,
                "high": float("inf"),
                "max": float("inf"),
                "oom_group": False,
                "usage": 0,
                "reclaimable": 0,
                "oom_kills": 0,
                "throttled_ms": 0
            }
        }
        self.procs = {}

    def create_cgroup(self, path, min_val=0, low_val=0, high_val=float("inf"), max_val=float("inf"), oom_group=False):
        if path in self.cgroups:
            return {"error": "ALREADY_EXISTS"}
        
        parts = path.rstrip("/").split("/")
        parent_path = "/".join(parts[:-1]) if len(parts) > 2 else "/"
        if parent_path not in self.cgroups:
            return {"error": "PARENT_NOT_FOUND"}
            
        self.cgroups[path] = {
            "path": path,
            "parent": parent_path,
            "children": set(),
            "min": min_val,
            "low": low_val,
            "high": high_val,
            "max": max_val,
            "oom_group": oom_group,
            "usage": 0,
            "reclaimable": 0,
            "oom_kills": 0,
            "throttled_ms": 0
        }
        self.cgroups[parent_path]["children"].add(path)
        return {"status": "CGROUP_CREATED", "path": path}

    def attach_process(self, cgroup_path, pid, initial_rss=0, oom_score_adj=0):
        if cgroup_path not in self.cgroups:
            return {"error": "CGROUP_NOT_FOUND"}
        self.procs[pid] = {
            "pid": pid,
            "cgroup": cgroup_path,
            "rss": initial_rss,
            "oom_score_adj": oom_score_adj
        }
        if initial_rss > 0:
            self._charge(cgroup_path, initial_rss, 0)
        return {"status": "PROCESS_ATTACHED", "pid": pid, "cgroup": cgroup_path}

    def _get_ancestors(self, path):
        ancestors = []
        curr = path
        while curr:
            ancestors.append(curr)
            curr = self.cgroups[curr]["parent"]
        return ancestors

    def _charge(self, cgroup_path, amount, reclaimable):
        ancestors = self._get_ancestors(cgroup_path)
        for p in ancestors:
            self.cgroups[p]["usage"] += amount
            self.cgroups[p]["reclaimable"] += reclaimable

    def _uncharge(self, cgroup_path, amount, reclaimable):
        ancestors = self._get_ancestors(cgroup_path)
        for p in ancestors:
            self.cgroups[p]["usage"] = max(0, self.cgroups[p]["usage"] - amount)
            self.cgroups[p]["reclaimable"] = max(0, self.cgroups[p]["reclaimable"] - reclaimable)

    def _trigger_reclaim(self, cgroup_path, needed):
        reclaimed = 0
        target = self.cgroups[cgroup_path]
        can_reclaim = min(needed, target["reclaimable"])
        if can_reclaim > 0:
            target["reclaimable"] -= can_reclaim
            target["usage"] -= can_reclaim
            curr = target["parent"]
            while curr:
                self.cgroups[curr]["usage"] -= can_reclaim
                self.cgroups[curr]["reclaimable"] -= can_reclaim
                curr = self.cgroups[curr]["parent"]
            reclaimed = can_reclaim
        return reclaimed

    def _trigger_oom(self, limiting_cgroup_path):
        candidates = []
        for pid, pinfo in self.procs.items():
            anc = self._get_ancestors(pinfo["cgroup"])
            if limiting_cgroup_path in anc:
                badness = pinfo["rss"] + (pinfo["oom_score_adj"] * 1000)
                candidates.append((badness, pid, pinfo))
                
        if not candidates:
            return None, 0, []

        candidates.sort(key=lambda x: x[0], reverse=True)
        victim_pid = candidates[0][1]
        victim_cgroup = candidates[0][2]["cgroup"]
        
        killed_pids = []
        freed_mem = 0
        
        if self.cgroups[victim_cgroup]["oom_group"]:
            for pid, pinfo in list(self.procs.items()):
                if pinfo["cgroup"] == victim_cgroup:
                    killed_pids.append(pid)
                    freed_mem += pinfo["rss"]
                    self._uncharge(victim_cgroup, pinfo["rss"], 0)
                    del self.procs[pid]
            self.cgroups[victim_cgroup]["oom_kills"] += len(killed_pids)
        else:
            killed_pids.append(victim_pid)
            freed_mem += candidates[0][2]["rss"]
            self._uncharge(victim_cgroup, candidates[0][2]["rss"], 0)
            del self.procs[victim_pid]
            self.cgroups[victim_cgroup]["oom_kills"] += 1
            
        return victim_pid, freed_mem, killed_pids

    def alloc_memory(self, pid, amount, reclaimable=0):
        if pid not in self.procs:
            return {"error": "PROCESS_NOT_FOUND"}
        pinfo = self.procs[pid]
        cg_path = pinfo["cgroup"]
        ancestors = self._get_ancestors(cg_path)
        
        events = []
        
        for anc_path in ancestors:
            cg = self.cgroups[anc_path]
            if cg["usage"] + amount > cg["max"]:
                needed = (cg["usage"] + amount) - cg["max"]
                reclaimed = self._trigger_reclaim(anc_path, needed)
                events.append({"event": "DIRECT_RECLAIM", "cgroup": anc_path, "reclaimed": reclaimed})
                
                if cg["usage"] + amount > cg["max"]:
                    victim, freed, killed = self._trigger_oom(anc_path)
                    events.append({
                        "event": "OOM_KILL",
                        "limiting_cgroup": anc_path,
                        "victim_pid": victim,
                        "killed_pids": killed,
                        "freed_memory": freed
                    })
                    if pid in killed:
                        return {
                            "status": "ALLOCATION_KILLED_BY_OOM",
                            "pid": pid,
                            "events": events
                        }

        self._charge(cg_path, amount, reclaimable)
        pinfo["rss"] += amount

        max_throttle = 0
        for anc_path in ancestors:
            cg = self.cgroups[anc_path]
            if cg["usage"] > cg["high"]:
                excess = cg["usage"] - cg["high"]
                delay = min(1000, int((excess * 100) / cg["high"]))
                cg["throttled_ms"] += delay
                max_throttle = max(max_throttle, delay)
                events.append({"event": "THROTTLED", "cgroup": anc_path, "delay_ms": delay})

        return {
            "status": "ALLOCATED",
            "pid": pid,
            "allocated_bytes": amount,
            "new_rss": pinfo["rss"],
            "throttle_delay_ms": max_throttle,
            "events": events
        }

    def free_memory(self, pid, amount):
        if pid not in self.procs:
            return {"error": "PROCESS_NOT_FOUND"}
        pinfo = self.procs[pid]
        freed = min(amount, pinfo["rss"])
        pinfo["rss"] -= freed
        self._uncharge(pinfo["cgroup"], freed, 0)
        return {"status": "FREED", "pid": pid, "freed_bytes": freed, "current_rss": pinfo["rss"]}

    def get_cgroup_state(self, path):
        if path not in self.cgroups:
            return {"error": "CGROUP_NOT_FOUND"}
        cg = self.cgroups[path]
        return {
            "path": path,
            "usage": cg["usage"],
            "reclaimable": cg["reclaimable"],
            "oom_kills": cg["oom_kills"],
            "throttled_ms": cg["throttled_ms"],
            "attached_processes": [
                {"pid": p["pid"], "rss": p["rss"]}
                for p in self.procs.values() if p["cgroup"] == path
            ]
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    engine = MemCgroupV2Engine()
    results = []
    
    for op in data["operations"]:
        opcode = op["op"]
        if opcode == "CREATE_CGROUP":
            res = engine.create_cgroup(
                op["path"],
                min_val=op.get("min", 0),
                low_val=op.get("low", 0),
                high_val=op.get("high", float("inf")),
                max_val=op.get("max", float("inf")),
                oom_group=op.get("oom_group", False)
            )
            results.append(res)
        elif opcode == "ATTACH_PROCESS":
            res = engine.attach_process(
                op["cgroup"],
                op["pid"],
                initial_rss=op.get("initial_rss", 0),
                oom_score_adj=op.get("oom_score_adj", 0)
            )
            results.append(res)
        elif opcode == "ALLOC_MEMORY":
            res = engine.alloc_memory(
                op["pid"],
                op["amount"],
                reclaimable=op.get("reclaimable", 0)
            )
            results.append(res)
        elif opcode == "FREE_MEMORY":
            res = engine.free_memory(
                op["pid"],
                op["amount"]
            )
            results.append(res)

    cgroup_states = {}
    for q in data.get("queries", []):
        cgroup_states[q] = engine.get_cgroup_state(q)

    total_kills = sum(cg["oom_kills"] for cg in engine.cgroups.values())
    output = {
        "results": results,
        "cgroup_states": cgroup_states,
        "summary": {
            "total_cgroups": len(engine.cgroups),
            "active_processes": len(engine.procs),
            "total_oom_kills": total_kills
        }
    }
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
