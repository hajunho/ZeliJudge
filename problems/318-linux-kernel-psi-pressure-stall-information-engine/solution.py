import sys
import os
import math
import json

class PSIEngine:
    def __init__(self, config: dict):
        self.current_time_us = 0
        self.resources = ["cpu", "memory", "io"]
        self.tasks = {}
        
        self.res_stats = {}
        for r in self.resources:
            self.res_stats[r] = {
                "some": {"total_us": 0, "avg10": 0.0, "avg60": 0.0, "avg300": 0.0},
                "full": {"total_us": 0, "avg10": 0.0, "avg60": 0.0, "avg300": 0.0},
                "history": []
            }

        self.triggers = []
        self.event_log = []
        self.history = []
        self.stats = {
            "time_steps": 0,
            "triggers_fired": 0,
            "total_some_stalls_us": {"cpu": 0, "memory": 0, "io": 0},
            "total_full_stalls_us": {"cpu": 0, "memory": 0, "io": 0}
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def register_task(self, pid: int):
        self.tasks[pid] = "IDLE"
        self.log(f"TASK_REGISTER pid={pid}")

    def set_task_state(self, pid: int, state: str):
        self.tasks[pid] = state
        self.log(f"TASK_STATE pid={pid} state={state}")

    def register_trigger(self, trig: dict):
        self.triggers.append({
            "trigger_id": trig["trigger_id"],
            "resource": trig["resource"],
            "type": trig["type"],
            "threshold_us": trig["threshold_us"],
            "window_us": trig["window_us"],
            "last_fired_us": -trig["window_us"],
            "events": []
        })
        self.log(f"TRIGGER_REGISTER id={trig['trigger_id']} res={trig['resource']} type={trig['type']} th={trig['threshold_us']} win={trig['window_us']}")

    def step_time(self, delta_us: int):
        if delta_us <= 0:
            return

        self.stats["time_steps"] += 1
        start_t = self.current_time_us
        end_t = start_t + delta_us
        self.current_time_us = end_t

        active_tasks = [s for s in self.tasks.values() if s != "IDLE"]
        total_active = len(active_tasks)

        for r in self.resources:
            stalled_tasks = [s for s in active_tasks if s == f"STALLED_{r.upper()}"]
            stalled_cnt = len(stalled_tasks)

            some_active = (stalled_cnt > 0)
            if r == "cpu":
                full_active = False
            else:
                full_active = (total_active > 0 and stalled_cnt == total_active)

            some_stall_us = delta_us if some_active else 0
            full_stall_us = delta_us if full_active else 0

            self.res_stats[r]["some"]["total_us"] += some_stall_us
            self.res_stats[r]["full"]["total_us"] += full_stall_us
            self.stats["total_some_stalls_us"][r] += some_stall_us
            self.stats["total_full_stalls_us"][r] += full_stall_us

            for mode, stall_amount in [("some", some_stall_us), ("full", full_stall_us)]:
                pct = (stall_amount / delta_us) * 100.0
                for win_sec, attr in [(10, "avg10"), (60, "avg60"), (300, "avg300")]:
                    tau = win_sec * 1_000_000
                    factor = math.exp(-delta_us / tau)
                    old_avg = self.res_stats[r][mode][attr]
                    new_avg = old_avg * factor + pct * (1.0 - factor)
                    self.res_stats[r][mode][attr] = round(new_avg, 2)

            self.res_stats[r]["history"].append({
                "time_us": end_t,
                "delta_us": delta_us,
                "some": some_active,
                "full": full_active
            })

            for trig in self.triggers:
                if trig["resource"] == r:
                    is_active = some_active if trig["type"] == "some" else full_active
                    if is_active:
                        trig["events"].append((end_t, delta_us))

                    win_start = end_t - trig["window_us"]
                    valid_events = []
                    sum_stall = 0
                    for ev_end, ev_dur in trig["events"]:
                        ev_start = ev_end - ev_dur
                        if ev_end <= win_start:
                            continue
                        overlap_start = max(ev_start, win_start)
                        overlap_end = ev_end
                        overlap = max(0, overlap_end - overlap_start)
                        if overlap > 0:
                            sum_stall += overlap
                            valid_events.append((ev_end, ev_dur))
                    trig["events"] = valid_events

                    if sum_stall >= trig["threshold_us"] and (end_t - trig["last_fired_us"] >= trig["window_us"]):
                        trig["last_fired_us"] = end_t
                        self.stats["triggers_fired"] += 1
                        self.log(f"TRIGGER_FIRED id={trig['trigger_id']} stall_us={sum_stall} at={end_t}")
                        self.history.append({
                            "op": "TRIGGER_FIRED",
                            "trigger_id": trig["trigger_id"],
                            "resource": r,
                            "type": trig["type"],
                            "stall_us": sum_stall,
                            "timestamp_us": end_t
                        })

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = PSIEngine(config)

    for op_info in operations:
        op = op_info.get("op")
        if op == "REGISTER_TASK":
            pid = op_info.get("pid")
            engine.register_task(pid)
        elif op == "SET_TASK_STATE":
            pid = op_info.get("pid")
            state = op_info.get("state", "IDLE")
            engine.set_task_state(pid, state)
        elif op == "REGISTER_TRIGGER":
            engine.register_trigger(op_info)
        elif op == "STEP_TIME":
            delta_us = op_info.get("delta_us", 0)
            engine.step_time(delta_us)

    pressure_dump = {}
    for r in engine.resources:
        pressure_dump[r] = {
            "some": {
                "avg10": engine.res_stats[r]["some"]["avg10"],
                "avg60": engine.res_stats[r]["some"]["avg60"],
                "avg300": engine.res_stats[r]["some"]["avg300"],
                "total_us": engine.res_stats[r]["some"]["total_us"]
            },
            "full": {
                "avg10": engine.res_stats[r]["full"]["avg10"],
                "avg60": engine.res_stats[r]["full"]["avg60"],
                "avg300": engine.res_stats[r]["full"]["avg300"],
                "total_us": engine.res_stats[r]["full"]["total_us"]
            }
        }

    return {
        "stats": engine.stats,
        "current_time_us": engine.current_time_us,
        "pressure": pressure_dump,
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
