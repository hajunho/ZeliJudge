import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class EASSimulation:
    def __init__(self, config):
        self.capacity_margin = config.get("capacity_margin", 0.8)
        self.energy_margin_mw = config.get("energy_margin_mw", 15)
        self.perf_domains = config.get("perf_domains", [])
        
        self.cpu_to_pd = {}
        self.cpu_max_cap = {}
        self.all_cpus = []
        for pd in self.perf_domains:
            for c in pd["cpus"]:
                self.cpu_to_pd[c] = pd
                self.cpu_max_cap[c] = pd["max_capacity"]
                self.all_cpus.append(c)
        self.all_cpus.sort()
        
        self.cpu_util = {c: 0 for c in self.all_cpus}
        self.active_tasks = {}
        
        self.eas_decisions = []
        self.event_logs = []
        self.cfs_fallback_count = 0
        self.eas_optimal_count = 0

    def is_overutilized(self):
        for c in self.all_cpus:
            if self.cpu_util[c] > self.capacity_margin * self.cpu_max_cap[c]:
                return True
        return False

    def _get_opp_for_util(self, pd, max_util):
        for opp in pd["opps"]:
            if opp["capacity"] >= max_util:
                return opp
        return pd["opps"][-1]

    def compute_system_energy(self, cand_cpu=None, task_util=0):
        total_power = 0.0
        for pd in self.perf_domains:
            proj_utils = {}
            for c in pd["cpus"]:
                u = self.cpu_util[c]
                if c == cand_cpu:
                    u += task_util
                proj_utils[c] = u
                
            max_u = max(proj_utils.values()) if proj_utils else 0
            opp = self._get_opp_for_util(pd, max_u)
            
            pd_power = 0.0
            opp_cap = opp["capacity"]
            opp_pwr = opp["power_mw"]
            for c, u in proj_utils.items():
                if opp_cap > 0:
                    pd_power += (u / opp_cap) * opp_pwr
            total_power += pd_power
        return total_power

    def update_cpu_util(self, current_time, cpu_id, util):
        if cpu_id in self.cpu_util:
            self.cpu_util[cpu_id] = util
            self.event_logs.append({
                "time": current_time,
                "event": "UPDATE_CPU_UTIL",
                "cpu_id": cpu_id,
                "new_util": util
            })

    def wakeup_task(self, current_time, task_id, task_util, prev_cpu):
        overutilized = self.is_overutilized()
        target_cpu = None
        decision_mode = None
        
        if overutilized:
            decision_mode = "FALLBACK_CFS"
            self.cfs_fallback_count += 1
            min_util = float("inf")
            best_c = prev_cpu
            for c in self.all_cpus:
                if self.cpu_util[c] < min_util:
                    min_util = self.cpu_util[c]
                    best_c = c
            target_cpu = best_c
        else:
            decision_mode = "EAS_ENERGY_OPTIMAL"
            self.eas_optimal_count += 1
            
            pd_candidates = []
            for pd in self.perf_domains:
                fitting_cpus = []
                for c in pd["cpus"]:
                    if self.cpu_util[c] + task_util <= self.capacity_margin * pd["max_capacity"]:
                        fitting_cpus.append(c)
                if fitting_cpus:
                    fitting_cpus.sort(key=lambda c: (self.cpu_util[c], 0 if c == prev_cpu else 1, c))
                    pd_candidates.append(fitting_cpus[0])
            
            if not pd_candidates:
                all_sorted = sorted(self.all_cpus, key=lambda c: (self.cpu_util[c], c))
                target_cpu = all_sorted[0]
            else:
                candidates = pd_candidates
                energy_map = {}
                for c in candidates:
                    energy_map[c] = self.compute_system_energy(c, task_util)
                
                best_cand = min(candidates, key=lambda c: energy_map[c])
                
                if prev_cpu in candidates:
                    energy_saving = energy_map[prev_cpu] - energy_map[best_cand]
                    if energy_saving > self.energy_margin_mw:
                        target_cpu = best_cand
                    else:
                        target_cpu = prev_cpu
                else:
                    target_cpu = best_cand
                    
        self.cpu_util[target_cpu] += task_util
        self.active_tasks[task_id] = {"cpu": target_cpu, "util": task_util}
        
        system_energy = self.compute_system_energy()
        
        decision = {
            "time": current_time,
            "task_id": task_id,
            "task_util": task_util,
            "prev_cpu": prev_cpu,
            "target_cpu": target_cpu,
            "decision_mode": decision_mode,
            "overutilized": overutilized,
            "estimated_system_power_mw": round(system_energy, 2)
        }
        self.eas_decisions.append(decision)
        self.event_logs.append({
            "time": current_time,
            "event": "WAKEUP_TASK",
            "task_id": task_id,
            "target_cpu": target_cpu,
            "decision_mode": decision_mode
        })

    def task_sleep(self, current_time, task_id):
        if task_id in self.active_tasks:
            info = self.active_tasks.pop(task_id)
            c = info["cpu"]
            u = info["util"]
            self.cpu_util[c] = max(0, self.cpu_util[c] - u)
            self.event_logs.append({
                "time": current_time,
                "event": "TASK_SLEEP",
                "task_id": task_id,
                "cpu_id": c
            })

    def run_trace(self, trace):
        for ev in trace:
            ev_type = ev.get("type")
            t = ev.get("time", 0)
            if ev_type == "WAKEUP_TASK":
                self.wakeup_task(t, ev["task_id"], ev["task_util"], ev["prev_cpu"])
            elif ev_type == "TASK_SLEEP":
                self.task_sleep(t, ev["task_id"])
            elif ev_type == "UPDATE_CPU_UTIL":
                self.update_cpu_util(t, ev["cpu_id"], ev["util"])

    def get_result(self):
        return {
            "summary": {
                "total_decisions": len(self.eas_decisions),
                "eas_optimal_count": self.eas_optimal_count,
                "cfs_fallback_count": self.cfs_fallback_count,
                "final_overutilized": self.is_overutilized(),
                "final_system_power_mw": round(self.compute_system_energy(), 2)
            },
            "cpu_utilizations": {str(k): v for k, v in self.cpu_util.items()},
            "eas_decisions": self.eas_decisions,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    sim = EASSimulation(config)
    sim.run_trace(trace)
    result = sim.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
