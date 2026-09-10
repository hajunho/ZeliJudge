import sys
import json

class SchedTopologyEngine:
    def __init__(self, config=None):
        config = config or {}
        self.cache_hot_timeout = config.get("cache_hot_timeout", 50)
        self.numa_imbalance_threshold = config.get("numa_imbalance_threshold", 50)
        
        self.cpus = {}
        self.tasks = {}
        
        self.tasks_migrated = 0
        self.cache_hot_migrations_blocked = 0
        self.balance_runs = 0
        
        self.migration_logs = []
        self.event_logs = []

    def init_topology(self, current_time, num_nodes, cores_per_node, smt_per_core):
        cpu_id = 0
        core_id = 0
        for n in range(num_nodes):
            for c in range(cores_per_node):
                for s in range(smt_per_core):
                    self.cpus[cpu_id] = {
                        "cpu_id": cpu_id,
                        "node_id": n,
                        "core_id": core_id,
                        "tasks": []
                    }
                    cpu_id += 1
                core_id += 1
        self.event_logs.append({
            "time": current_time,
            "event": "TOPOLOGY_INITIALIZED",
            "total_cpus": len(self.cpus),
            "num_nodes": num_nodes
        })

    def enqueue_task(self, current_time, task_id, load, target_cpu):
        if target_cpu not in self.cpus:
            return
        t = {
            "task_id": task_id,
            "load": load,
            "cpu_id": target_cpu,
            "last_run_time": current_time
        }
        self.tasks[task_id] = t
        self.cpus[target_cpu]["tasks"].append(task_id)
        self.event_logs.append({
            "time": current_time,
            "event": "TASK_ENQUEUED",
            "task_id": task_id,
            "load": load,
            "cpu_id": target_cpu
        })

    def execute_task(self, current_time, task_id, duration):
        if task_id in self.tasks:
            t = self.tasks[task_id]
            t["last_run_time"] = current_time + duration
            self.event_logs.append({
                "time": current_time,
                "event": "TASK_EXECUTED",
                "task_id": task_id,
                "duration": duration,
                "finish_time": t["last_run_time"]
            })

    def dequeue_task(self, current_time, task_id):
        if task_id in self.tasks:
            t = self.tasks[task_id]
            c = self.cpus[t["cpu_id"]]
            if task_id in c["tasks"]:
                c["tasks"].remove(task_id)
            del self.tasks[task_id]
            self.event_logs.append({
                "time": current_time,
                "event": "TASK_DEQUEUED",
                "task_id": task_id
            })

    def _cpu_load(self, cpu_id):
        return sum(self.tasks[tid]["load"] for tid in self.cpus[cpu_id]["tasks"])

    def trigger_load_balance(self, current_time, level, idle_cpu):
        if idle_cpu not in self.cpus:
            return
        self.balance_runs += 1
        idle_c = self.cpus[idle_cpu]
        
        candidate_cpus = []
        if level == "SMT":
            candidate_cpus = [cid for cid, c in self.cpus.items() if c["core_id"] == idle_c["core_id"] and cid != idle_cpu]
        elif level == "MC":
            candidate_cpus = [cid for cid, c in self.cpus.items() if c["node_id"] == idle_c["node_id"] and c["core_id"] != idle_c["core_id"]]
        elif level == "NUMA":
            candidate_cpus = [cid for cid, c in self.cpus.items() if c["node_id"] != idle_c["node_id"]]
            
        if not candidate_cpus:
            return
            
        busiest_cpu = max(candidate_cpus, key=lambda cid: self._cpu_load(cid))
        busiest_load = self._cpu_load(busiest_cpu)
        idle_load = self._cpu_load(idle_cpu)
        
        if busiest_load <= idle_load:
            return
            
        imbalance = (busiest_load - idle_load) // 2
        if level == "NUMA" and imbalance < self.numa_imbalance_threshold:
            return
            
        busiest_tasks = self.cpus[busiest_cpu]["tasks"]
        if not busiest_tasks:
            return
            
        chosen_task_id = None
        for tid in reversed(busiest_tasks):
            t = self.tasks[tid]
            is_cache_hot = (current_time - t["last_run_time"]) < self.cache_hot_timeout
            if not is_cache_hot:
                chosen_task_id = tid
                break
                
        if chosen_task_id is None:
            if idle_load == 0:
                chosen_task_id = busiest_tasks[-1]
            else:
                self.cache_hot_migrations_blocked += 1
                self.event_logs.append({
                    "time": current_time,
                    "event": "MIGRATION_BLOCKED_CACHE_HOT",
                    "busiest_cpu": busiest_cpu,
                    "idle_cpu": idle_cpu
                })
                return
                
        t = self.tasks[chosen_task_id]
        self.cpus[busiest_cpu]["tasks"].remove(chosen_task_id)
        self.cpus[idle_cpu]["tasks"].append(chosen_task_id)
        t["cpu_id"] = idle_cpu
        self.tasks_migrated += 1
        
        self.migration_logs.append({
            "time": current_time,
            "task_id": chosen_task_id,
            "from_cpu": busiest_cpu,
            "to_cpu": idle_cpu,
            "level": level,
            "imbalance_cleared": t["load"]
        })
        self.event_logs.append({
            "time": current_time,
            "event": "TASK_MIGRATED",
            "task_id": chosen_task_id,
            "from_cpu": busiest_cpu,
            "to_cpu": idle_cpu,
            "level": level
        })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "INIT_TOPOLOGY":
                self.init_topology(t, ev["num_nodes"], ev["cores_per_node"], ev["smt_per_core"])
            elif ev_type == "ENQUEUE_TASK":
                self.enqueue_task(t, ev["task_id"], ev["load"], ev["target_cpu"])
            elif ev_type == "EXECUTE_TASK":
                self.execute_task(t, ev["task_id"], ev["duration"])
            elif ev_type == "DEQUEUE_TASK":
                self.dequeue_task(t, ev["task_id"])
            elif ev_type == "TRIGGER_LOAD_BALANCE":
                self.trigger_load_balance(t, ev["level"], ev["idle_cpu"])

    def get_result(self):
        cpus_out = {}
        for cid, c in sorted(self.cpus.items()):
            cpus_out[f"cpu_{cid}"] = {
                "node_id": c["node_id"],
                "core_id": c["core_id"],
                "total_load": self._cpu_load(cid),
                "tasks": list(c["tasks"])
            }
            
        return {
            "summary": {
                "tasks_migrated": self.tasks_migrated,
                "cache_hot_migrations_blocked": self.cache_hot_migrations_blocked,
                "balance_runs": self.balance_runs,
                "total_cpus": len(self.cpus),
                "active_tasks": len(self.tasks)
            },
            "cpus": cpus_out,
            "migration_logs": self.migration_logs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = SchedTopologyEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
