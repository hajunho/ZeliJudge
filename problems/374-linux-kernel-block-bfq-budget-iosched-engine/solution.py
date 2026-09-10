import json
import sys

# Ensure UTF-8 input/output on Windows
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
        
    payload = json.loads(raw_data)
    config = payload.get("config", {})
    default_budget_sectors = int(config.get("default_budget_sectors", 64))
    sector_service_time_ns = int(config.get("sector_service_time_ns", 1000))
    interactive_weight_boost = float(config.get("interactive_boost_factor", 2.0))
    
    queues_input = payload.get("queues", [])
    operations = payload.get("operations", [])
    
    queues = {}
    for q in queues_input:
        qid = q["id"]
        w = float(q.get("weight", 100.0))
        is_interactive = bool(q.get("interactive", False))
        eff_weight = w * interactive_weight_boost if is_interactive else w
        b = int(q.get("budget_sectors", default_budget_sectors))
        queues[qid] = {
            "id": qid,
            "weight": w,
            "eff_weight": eff_weight,
            "is_interactive": is_interactive,
            "budget": b,
            "remaining_budget": b,
            "virtual_start": 0.0,
            "virtual_finish": 0.0,
            "is_active": False,
            "requests": [],
            "served_requests": 0,
            "served_sectors": 0,
            "total_service_time_ns": 0,
            "preemptions_triggered": 0
        }
        
    current_time_ns = 0
    virtual_time = 0.0
    active_queue_id = None
    device_busy_until_ns = 0
    
    history_events = []
    
    def select_next_queue():
        nonlocal virtual_time
        eligible = [q for q in queues.values() if q["is_active"] and len(q["requests"]) > 0]
        if not eligible:
            return None
            
        min_vs = min(q["virtual_start"] for q in eligible)
        if virtual_time < min_vs:
            virtual_time = min_vs
            
        ready = [q for q in eligible if q["virtual_start"] <= virtual_time + 1e-9]
        if not ready:
            ready = eligible
            
        chosen = min(ready, key=lambda q: (0 if q["is_interactive"] else 1, q["virtual_finish"], q["id"]))
        return chosen["id"]

    def dispatch_one_request(now_ns):
        nonlocal active_queue_id, device_busy_until_ns, virtual_time
        if active_queue_id is None:
            active_queue_id = select_next_queue()
            if active_queue_id is None:
                return False
            queues[active_queue_id]["remaining_budget"] = queues[active_queue_id]["budget"]
            
        curr_q = queues[active_queue_id]
        if not curr_q["requests"]:
            curr_q["is_active"] = False
            active_queue_id = None
            return False
            
        req = curr_q["requests"].pop(0)
        sec = req["sectors"]
        
        start_ns = max(now_ns, device_busy_until_ns)
        duration_ns = sec * sector_service_time_ns
        comp_ns = start_ns + duration_ns
        device_busy_until_ns = comp_ns
        
        curr_q["served_requests"] += 1
        curr_q["served_sectors"] += sec
        curr_q["total_service_time_ns"] += duration_ns
        curr_q["remaining_budget"] -= sec
        
        v_delta = sec / curr_q["eff_weight"]
        virtual_time += v_delta
        
        history_events.append({
            "time_ns": start_ns,
            "complete_ns": comp_ns,
            "queue": curr_q["id"],
            "req_id": req["id"],
            "sectors": sec,
            "remaining_budget": curr_q["remaining_budget"],
            "virtual_time": round(virtual_time, 4)
        })
        
        if curr_q["remaining_budget"] <= 0 or not curr_q["requests"]:
            if curr_q["requests"]:
                curr_q["virtual_start"] = max(virtual_time, curr_q["virtual_finish"])
                curr_q["virtual_finish"] = curr_q["virtual_start"] + (curr_q["budget"] / curr_q["eff_weight"])
                curr_q["remaining_budget"] = curr_q["budget"]
            else:
                curr_q["is_active"] = False
            active_queue_id = None
            
        return True

    for op in operations:
        op_type = op["type"]
        if op_type == "ENQUEUE_IO":
            qid = op["queue"]
            req_id = op["req_id"]
            sec = int(op["sectors"])
            t_ns = int(op.get("time_ns", current_time_ns))
            
            while current_time_ns < t_ns:
                if device_busy_until_ns > current_time_ns:
                    current_time_ns = min(t_ns, device_busy_until_ns)
                else:
                    if not dispatch_one_request(current_time_ns):
                        current_time_ns = t_ns
                        break
                    current_time_ns = min(t_ns, device_busy_until_ns)
                    
            current_time_ns = t_ns
            
            if qid in queues:
                q = queues[qid]
                was_empty = (len(q["requests"]) == 0 and not q["is_active"])
                q["requests"].append({"id": req_id, "sectors": sec, "arrival_ns": t_ns})
                if was_empty:
                    q["is_active"] = True
                    q["virtual_start"] = max(virtual_time, q["virtual_finish"])
                    q["virtual_finish"] = q["virtual_start"] + (q["budget"] / q["eff_weight"])
                    q["remaining_budget"] = q["budget"]
                    
                    if q["is_interactive"] and active_queue_id and not queues[active_queue_id]["is_interactive"]:
                        q["preemptions_triggered"] += 1
                        active_queue_id = q["id"]
                        
        elif op_type == "ADVANCE_TIME":
            target_ns = int(op["to_time_ns"])
            while current_time_ns < target_ns:
                if device_busy_until_ns > current_time_ns:
                    current_time_ns = min(target_ns, device_busy_until_ns)
                else:
                    if not dispatch_one_request(current_time_ns):
                        current_time_ns = target_ns
                        break
                    current_time_ns = min(target_ns, device_busy_until_ns)
                    
            current_time_ns = target_ns

    final_time = max(current_time_ns, device_busy_until_ns)
    
    queue_summaries = {}
    for qid, q in queues.items():
        queue_summaries[qid] = {
            "weight": q["weight"],
            "is_interactive": q["is_interactive"],
            "served_requests": q["served_requests"],
            "served_sectors": q["served_sectors"],
            "pending_requests": len(q["requests"]),
            "total_service_time_ns": q["total_service_time_ns"],
            "preemptions_triggered": q["preemptions_triggered"],
            "virtual_finish": round(q["virtual_finish"], 4)
        }
        
    result = {
        "final_time_ns": final_time,
        "virtual_time": round(virtual_time, 4),
        "total_dispatched_requests": len(history_events),
        "queues": queue_summaries,
        "history": history_events[:10]
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
