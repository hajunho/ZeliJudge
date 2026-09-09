import sys
import json
import math

import copy

def simulate_loadavg(data):
    data = copy.deepcopy(data)
    config = data.get("system_config", {})
    cpu_cores = config.get("cpu_cores", 4)
    dt = float(config.get("sampling_interval_sec", 5))
    
    initial = data.get("initial_loadavg", {})
    load1 = float(initial.get("load1", 0.0))
    load5 = float(initial.get("load5", 0.0))
    load15 = float(initial.get("load15", 0.0))
    
    c1 = math.exp(-dt / 60.0)
    c5 = math.exp(-dt / 300.0)
    c15 = math.exp(-dt / 900.0)
    
    ticks = data.get("ticks", [])
    
    history = []
    signal_results = []
    
    total_r = 0
    total_d = 0
    max_load1 = load1
    
    stuck_d_pids = set()
    
    for tick in ticks:
        t = tick["time"]
        procs = tick.get("processes", [])
        sig_info = tick.get("signal_sent")
        
        # Track D state PIDs
        for p in procs:
            if p["state"] == "D":
                stuck_d_pids.add(p["pid"])
                
        # 1. Process signal event if present
        if sig_info:
            target_pid = sig_info["pid"]
            sig = sig_info.get("signal", "SIGKILL")
            target_p = next((p for p in procs if p["pid"] == target_pid), None)
            if target_p:
                if target_p["state"] == "D":
                    signal_results.append({
                        "time": t,
                        "pid": target_pid,
                        "signal": sig,
                        "state": "D",
                        "result": "SIGNAL_IGNORED_D_STATE",
                        "explanation": "Process in TASK_UNINTERRUPTIBLE ignores all signals including SIGKILL"
                    })
                else:
                    signal_results.append({
                        "time": t,
                        "pid": target_pid,
                        "signal": sig,
                        "state": target_p["state"],
                        "result": "TERMINATED",
                        "explanation": f"Process terminated by {sig}"
                    })
                    target_p["state"] = "Z"
            else:
                signal_results.append({
                    "time": t,
                    "pid": target_pid,
                    "signal": sig,
                    "state": "UNKNOWN",
                    "result": "NOT_FOUND",
                    "explanation": "PID not found"
                })
                
        # 2. Count process states
        r_count = sum(1 for p in procs if p["state"] == "R")
        d_count = sum(1 for p in procs if p["state"] == "D")
        s_count = sum(1 for p in procs if p["state"] == "S")
        z_count = sum(1 for p in procs if p["state"] == "Z")
        
        total_r += r_count
        total_d += d_count
        
        # In Linux, active tasks = R + D
        active_tasks = r_count + d_count
        
        # 3. EMA update
        load1 = load1 * c1 + active_tasks * (1.0 - c1)
        load5 = load5 * c5 + active_tasks * (1.0 - c5)
        load15 = load15 * c15 + active_tasks * (1.0 - c15)
        
        max_load1 = max(max_load1, load1)
        
        if d_count > r_count and d_count > 0:
            diag = "IO_STORAGE_BOTTLENECK"
        elif r_count > cpu_cores:
            diag = "CPU_COMPUTE_BOTTLENECK"
        else:
            diag = "HEALTHY_WITHIN_CAPACITY"
            
        history.append({
            "time": t,
            "counts": {
                "R": r_count,
                "D": d_count,
                "S": s_count,
                "Z": z_count,
                "active": active_tasks
            },
            "loadavg": {
                "load1": round(load1, 4),
                "load5": round(load5, 4),
                "load15": round(load15, 4)
            },
            "diagnosis": diag
        })
        
    num_ticks = len(ticks) if ticks else 1
    if total_d > total_r and total_d > 0:
        primary_bottleneck = "IO_STORAGE_BOTTLENECK"
    elif total_r > (cpu_cores * num_ticks):
        primary_bottleneck = "CPU_COMPUTE_BOTTLENECK"
    else:
        primary_bottleneck = "HEALTHY_WITHIN_CAPACITY"
        
    summary = {
        "final_loadavg": {
            "load1": round(load1, 2),
            "load5": round(load5, 2),
            "load15": round(load15, 2)
        },
        "max_load1": round(max_load1, 2),
        "primary_bottleneck": primary_bottleneck,
        "unkillable_d_processes": sorted(list(stuck_d_pids)),
        "signal_events": signal_results
    }
    
    return {
        "summary": summary,
        "tick_history": history
    }

def main():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return
    data = json.loads(input_data)
    out = simulate_loadavg(data)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
