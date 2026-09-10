import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class MembarrierEngine:
    def __init__(self, config):
        self.num_cpus = config.get("num_cpus", 8)
        
        self.cpus = {
            i: {
                "cpu_id": i,
                "curr_pid": None,
                "curr_mm": None,
                "is_idle": True,
                "barriers": 0,
                "sync_cores": 0
            } for i in range(self.num_cpus)
        }
        
        self.threads = {}
        self.mms = {}
        
        self.total_membarrier_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.total_ipis_sent = 0
        self.targeted_ipis_sent = 0
        self.global_ipis_sent = 0
        self.sync_core_flushes = 0
        self.context_switch_barriers = 0
        self.call_logs = []
        self.event_logs = []

    def create_process(self, current_time, pid, mm_id):
        self.threads[pid] = mm_id
        if mm_id not in self.mms:
            self.mms[mm_id] = {"state": 0, "pids": set()}
        self.mms[mm_id]["pids"].add(pid)
        self.event_logs.append({
            "time": current_time,
            "event": "CREATE_PROCESS",
            "pid": pid,
            "mm_id": mm_id
        })

    def context_switch(self, current_time, cpu_id, pid):
        if cpu_id not in self.cpus or pid not in self.threads:
            return
        cpu = self.cpus[cpu_id]
        new_mm = self.threads[pid]
        cpu["curr_pid"] = pid
        cpu["curr_mm"] = new_mm
        cpu["is_idle"] = False
        
        mm_obj = self.mms.get(new_mm)
        if mm_obj and (mm_obj["state"] & 1):
            cpu["barriers"] += 1
            self.context_switch_barriers += 1
            
        self.event_logs.append({
            "time": current_time,
            "event": "CONTEXT_SWITCH",
            "cpu_id": cpu_id,
            "pid": pid,
            "mm_id": new_mm
        })

    def set_cpu_idle(self, current_time, cpu_id, is_idle=True):
        if cpu_id in self.cpus:
            self.cpus[cpu_id]["is_idle"] = is_idle
            if is_idle:
                self.cpus[cpu_id]["curr_pid"] = None
                self.cpus[cpu_id]["curr_mm"] = None
            self.event_logs.append({
                "time": current_time,
                "event": "SET_CPU_IDLE",
                "cpu_id": cpu_id,
                "is_idle": is_idle
            })

    def sys_membarrier(self, current_time, cpu_id, pid, cmd, flags=0):
        self.total_membarrier_calls += 1
        if pid not in self.threads:
            self.failed_calls += 1
            return -3
            
        mm_id = self.threads[pid]
        mm_obj = self.mms.get(mm_id)
        if not mm_obj:
            self.failed_calls += 1
            return -22
            
        ret = 0
        ipi_targets = []
        sync_core_applied = False
        
        if cmd == "MEMBARRIER_CMD_QUERY":
            ret = 0x7F
            self.successful_calls += 1
        elif cmd == "MEMBARRIER_CMD_GLOBAL":
            for c_id, cpu in self.cpus.items():
                if c_id != cpu_id and not cpu["is_idle"]:
                    ipi_targets.append(c_id)
                    cpu["barriers"] += 1
            self.cpus[cpu_id]["barriers"] += 1
            self.global_ipis_sent += len(ipi_targets)
            self.total_ipis_sent += len(ipi_targets)
            self.successful_calls += 1
        elif cmd == "MEMBARRIER_CMD_REGISTER_PRIVATE_EXPEDITED":
            mm_obj["state"] |= 1
            self.successful_calls += 1
        elif cmd == "MEMBARRIER_CMD_PRIVATE_EXPEDITED":
            if not (mm_obj["state"] & 1):
                self.failed_calls += 1
                ret = -1
            else:
                for c_id, cpu in self.cpus.items():
                    if c_id != cpu_id and cpu["curr_mm"] == mm_id:
                        ipi_targets.append(c_id)
                        cpu["barriers"] += 1
                self.cpus[cpu_id]["barriers"] += 1
                self.targeted_ipis_sent += len(ipi_targets)
                self.total_ipis_sent += len(ipi_targets)
                self.successful_calls += 1
        elif cmd == "MEMBARRIER_CMD_REGISTER_PRIVATE_EXPEDITED_SYNC_CORE":
            mm_obj["state"] |= 2
            self.successful_calls += 1
        elif cmd == "MEMBARRIER_CMD_PRIVATE_EXPEDITED_SYNC_CORE":
            if not (mm_obj["state"] & 2):
                self.failed_calls += 1
                ret = -1
            else:
                sync_core_applied = True
                for c_id, cpu in self.cpus.items():
                    if c_id != cpu_id and cpu["curr_mm"] == mm_id:
                        ipi_targets.append(c_id)
                        cpu["barriers"] += 1
                        cpu["sync_cores"] += 1
                        self.sync_core_flushes += 1
                self.cpus[cpu_id]["barriers"] += 1
                self.cpus[cpu_id]["sync_cores"] += 1
                self.sync_core_flushes += 1
                self.targeted_ipis_sent += len(ipi_targets)
                self.total_ipis_sent += len(ipi_targets)
                self.successful_calls += 1
        else:
            self.failed_calls += 1
            ret = -22
            
        ipi_targets.sort()
        log_entry = {
            "time": current_time,
            "caller_cpu": cpu_id,
            "caller_pid": pid,
            "caller_mm": mm_id,
            "cmd": cmd,
            "return_code": ret,
            "ipi_targets": ipi_targets,
            "ipis_sent_count": len(ipi_targets),
            "sync_core": sync_core_applied
        }
        self.call_logs.append(log_entry)
        return ret

    def run_trace(self, trace):
        for ev in trace:
            ev_type = ev.get("type")
            t = ev.get("time", 0)
            if ev_type == "CREATE_PROCESS":
                self.create_process(t, ev["pid"], ev["mm_id"])
            elif ev_type == "CONTEXT_SWITCH":
                self.context_switch(t, ev["cpu_id"], ev["pid"])
            elif ev_type == "SET_CPU_IDLE":
                self.set_cpu_idle(t, ev["cpu_id"], ev.get("is_idle", True))
            elif ev_type == "SYS_MEMBARRIER":
                self.sys_membarrier(t, ev["cpu_id"], ev["pid"], ev["cmd"], ev.get("flags", 0))

    def get_result(self):
        return {
            "summary": {
                "total_membarrier_calls": self.total_membarrier_calls,
                "successful_calls": self.successful_calls,
                "failed_calls": self.failed_calls,
                "total_ipis_sent": self.total_ipis_sent,
                "targeted_ipis_sent": self.targeted_ipis_sent,
                "global_ipis_sent": self.global_ipis_sent,
                "sync_core_flushes": self.sync_core_flushes,
                "context_switch_barriers": self.context_switch_barriers
            },
            "mms": {str(k): {"state": v["state"], "pids": sorted(list(v["pids"]))} for k, v in self.mms.items()},
            "call_logs": self.call_logs,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = MembarrierEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
