import sys
import json

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    num_cpus = input_data.get("num_cpus", 4)
    cpus_per_node = input_data.get("cpus_per_node", 2)
    stall_timeout_ticks = input_data.get("stall_timeout_ticks", 5)
    operations = input_data.get("operations", [])
    
    gp_seq = 0
    gp_active = False
    gp_start_tick = 0
    current_tick = 0
    
    cpu_state = {}
    for c in range(num_cpus):
        cpu_state[c] = {
            "read_depth": 0,
            "qs_reported": False,
            "callbacks_next": [],
            "callbacks_wait": [],
            "callbacks_done": []
        }
        
    stats = {
        "grace_periods_completed": 0,
        "callbacks_queued": 0,
        "callbacks_invoked": 0,
        "qs_reports_accepted": 0,
        "qs_reports_blocked_in_reader": 0,
        "rcu_stalls_detected": 0
    }
    
    op_log = []
    
    def check_gp_completion():
        nonlocal gp_active, gp_seq
        if not gp_active:
            return False
            
        all_quiesced = all(cpu_state[c]["qs_reported"] for c in range(num_cpus))
        if all_quiesced:
            gp_active = False
            gp_seq += 1
            stats["grace_periods_completed"] += 1
            
            for c in range(num_cpus):
                cpu_state[c]["callbacks_done"].extend(cpu_state[c]["callbacks_wait"])
                cpu_state[c]["callbacks_wait"] = []
                cpu_state[c]["qs_reported"] = False
                
            return True
        return False

    for op in operations:
        op_type = op.get("op")
        
        if op_type == "RCU_READ_LOCK":
            c = op["cpu"]
            cpu_state[c]["read_depth"] += 1
            op_log.append({
                "op": "RCU_READ_LOCK",
                "cpu": c,
                "read_depth": cpu_state[c]["read_depth"]
            })
            
        elif op_type == "RCU_READ_UNLOCK":
            c = op["cpu"]
            if cpu_state[c]["read_depth"] > 0:
                cpu_state[c]["read_depth"] -= 1
            op_log.append({
                "op": "RCU_READ_UNLOCK",
                "cpu": c,
                "read_depth": cpu_state[c]["read_depth"]
            })
            
        elif op_type == "CALL_RCU":
            c = op["cpu"]
            cb_id = op["callback_id"]
            stats["callbacks_queued"] += 1
            if gp_active:
                cpu_state[c]["callbacks_next"].append(cb_id)
            else:
                cpu_state[c]["callbacks_wait"].append(cb_id)
            op_log.append({
                "op": "CALL_RCU",
                "cpu": c,
                "callback_id": cb_id,
                "gp_active": gp_active
            })
            
        elif op_type == "START_GRACE_PERIOD":
            if not gp_active:
                gp_active = True
                gp_start_tick = current_tick
                for c in range(num_cpus):
                    cpu_state[c]["callbacks_wait"].extend(cpu_state[c]["callbacks_next"])
                    cpu_state[c]["callbacks_next"] = []
                    cpu_state[c]["qs_reported"] = False
                op_log.append({
                    "op": "START_GRACE_PERIOD",
                    "gp_seq": gp_seq,
                    "status": "GP_STARTED"
                })
            else:
                op_log.append({
                    "op": "START_GRACE_PERIOD",
                    "status": "GP_ALREADY_IN_PROGRESS"
                })
                
        elif op_type == "REPORT_QS":
            c = op["cpu"]
            if cpu_state[c]["read_depth"] > 0:
                stats["qs_reports_blocked_in_reader"] += 1
                op_log.append({
                    "op": "REPORT_QS",
                    "cpu": c,
                    "status": "REJECTED_BLOCKED_IN_RCU_READER",
                    "read_depth": cpu_state[c]["read_depth"]
                })
            else:
                stats["qs_reports_accepted"] += 1
                cpu_state[c]["qs_reported"] = True
                completed = check_gp_completion()
                op_log.append({
                    "op": "REPORT_QS",
                    "cpu": c,
                    "status": "QS_ACCEPTED",
                    "gp_completed": completed,
                    "new_gp_seq": gp_seq
                })
                
        elif op_type == "INVOKE_CALLBACKS":
            c = op["cpu"]
            invoked = list(cpu_state[c]["callbacks_done"])
            stats["callbacks_invoked"] += len(invoked)
            cpu_state[c]["callbacks_done"] = []
            op_log.append({
                "op": "INVOKE_CALLBACKS",
                "cpu": c,
                "invoked_count": len(invoked),
                "invoked_callbacks": invoked
            })
            
        elif op_type == "TICK":
            current_tick += 1
            stalled_cpus = []
            if gp_active and (current_tick - gp_start_tick) >= stall_timeout_ticks:
                for c in range(num_cpus):
                    if not cpu_state[c]["qs_reported"]:
                        stalled_cpus.append(c)
                if stalled_cpus:
                    stats["rcu_stalls_detected"] += 1
                    
            op_log.append({
                "op": "TICK",
                "tick": current_tick,
                "gp_active": gp_active,
                "stalled_cpus": stalled_cpus
            })

    per_cpu_summary = {}
    for c in range(num_cpus):
        per_cpu_summary[f"cpu_{c}"] = {
            "read_depth": cpu_state[c]["read_depth"],
            "qs_reported": cpu_state[c]["qs_reported"],
            "pending_wait_cb_count": len(cpu_state[c]["callbacks_wait"]),
            "pending_done_cb_count": len(cpu_state[c]["callbacks_done"])
        }

    res = {
        "num_cpus": num_cpus,
        "cpus_per_node": cpus_per_node,
        "final_gp_seq": gp_seq,
        "gp_active": gp_active,
        "per_cpu_summary": per_cpu_summary,
        "stats": stats,
        "op_log": op_log
    }
    
    sys.stdout.write(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    solve()
