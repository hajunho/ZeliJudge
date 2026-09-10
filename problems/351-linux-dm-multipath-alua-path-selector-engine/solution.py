import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
        
    input_data = json.loads(raw_input)
    config = input_data.get("multipath_config", {})
    queue_if_no_path = config.get("queue_if_no_path", True)
    selector_policy = config.get("path_selector", "round-robin")
    failback_mode = config.get("failback", "immediate")
    
    priority_groups = input_data.get("priority_groups", [])
    pg_list = sorted(priority_groups, key=lambda x: x.get("priority", 0), reverse=True)
    
    path_states = {}
    for pg in pg_list:
        for p in pg.get("paths", []):
            pid = p["path_id"]
            path_states[pid] = {
                "path_id": pid,
                "pg_id": pg["pg_id"],
                "alua_state": pg.get("alua_state", "active/optimized"),
                "priority": pg.get("priority", 10),
                "state": p.get("initial_state", "UP"),
                "throughput_weight": max(1, p.get("throughput_weight", 100)),
                "inflight_ios": 0,
                "inflight_bytes": 0,
                "total_dispatched_ios": 0,
                "total_dispatched_bytes": 0
            }

    timeline = input_data.get("events_and_io_timeline", [])
    
    trace = []
    current_active_pg_id = pg_list[0]["pg_id"] if pg_list else None
    rr_pointer = 0
    queued_ios = []
    
    for step in timeline:
        step_id = step.get("step", 0)
        events = step.get("path_events", [])
        incoming_ios = step.get("incoming_ios", [])
        completed_ios = step.get("completed_ios", [])
        
        # 1. Process completions
        for c_io in completed_ios:
            p_id = c_io.get("path_id")
            c_bytes = c_io.get("bytes", 4096)
            if p_id in path_states:
                path_states[p_id]["inflight_ios"] = max(0, path_states[p_id]["inflight_ios"] - 1)
                path_states[p_id]["inflight_bytes"] = max(0, path_states[p_id]["inflight_bytes"] - c_bytes)
                
        # 2. Process path events
        for ev in events:
            p_id = ev.get("path_id")
            new_st = ev.get("new_state")
            if p_id in path_states and new_st in ["UP", "DOWN"]:
                path_states[p_id]["state"] = new_st
                
        # 3. Determine active Priority Group
        candidate_pg = None
        for pg in pg_list:
            pg_id = pg["pg_id"]
            up_paths = [p["path_id"] for p in pg.get("paths", []) if path_states[p["path_id"]]["state"] == "UP"]
            if up_paths:
                candidate_pg = pg_id
                break
                
        pg_switched = False
        if candidate_pg is not None:
            if current_active_pg_id != candidate_pg:
                current_pri = next((pg["priority"] for pg in pg_list if pg["pg_id"] == current_active_pg_id), -1)
                candidate_pri = next((pg["priority"] for pg in pg_list if pg["pg_id"] == candidate_pg), -1)
                
                if candidate_pri > current_pri:
                    if failback_mode == "immediate":
                        current_active_pg_id = candidate_pg
                        pg_switched = True
                else:
                    current_active_pg_id = candidate_pg
                    pg_switched = True
        else:
            current_active_pg_id = None
            
        # 4. Dispatch I/Os
        io_queue = queued_ios + incoming_ios
        queued_ios = []
        dispatched_step = []
        failed_step = []
        
        if current_active_pg_id is not None:
            active_pg_obj = next(pg for pg in pg_list if pg["pg_id"] == current_active_pg_id)
            active_up_paths = [p["path_id"] for p in active_pg_obj.get("paths", []) if path_states[p["path_id"]]["state"] == "UP"]
        else:
            active_up_paths = []
            
        for io in io_queue:
            io_id = io.get("io_id")
            io_bytes = io.get("bytes", 4096)
            
            if not active_up_paths:
                if queue_if_no_path:
                    queued_ios.append(io)
                else:
                    failed_step.append({
                        "io_id": io_id,
                        "status": "FAILED_EIO",
                        "reason": "NO_PATH_AVAILABLE"
                    })
                continue
                
            chosen_path = None
            if selector_policy == "round-robin":
                chosen_path = active_up_paths[rr_pointer % len(active_up_paths)]
                rr_pointer += 1
            elif selector_policy == "queue-length":
                chosen_path = min(active_up_paths, key=lambda pid: (path_states[pid]["inflight_ios"], pid))
            elif selector_policy == "service-time":
                chosen_path = min(active_up_paths, key=lambda pid: (path_states[pid]["inflight_bytes"] / path_states[pid]["throughput_weight"], pid))
            else:
                chosen_path = active_up_paths[0]
                
            path_states[chosen_path]["inflight_ios"] += 1
            path_states[chosen_path]["inflight_bytes"] += io_bytes
            path_states[chosen_path]["total_dispatched_ios"] += 1
            path_states[chosen_path]["total_dispatched_bytes"] += io_bytes
            
            dispatched_step.append({
                "io_id": io_id,
                "dispatched_path": chosen_path,
                "pg_id": current_active_pg_id,
                "bytes": io_bytes
            })
            
        trace.append({
            "step": step_id,
            "active_pg": current_active_pg_id,
            "pg_switched": pg_switched,
            "available_paths_count": len(active_up_paths),
            "dispatched_count": len(dispatched_step),
            "queued_count": len(queued_ios),
            "failed_count": len(failed_step),
            "dispatches": dispatched_step,
            "failed_ios": failed_step
        })

    total_ios_dispatched = sum(p["total_dispatched_ios"] for p in path_states.values())
    total_bytes_dispatched = sum(p["total_dispatched_bytes"] for p in path_states.values())
    
    result = {
        "mpath_summary": {
            "selector_policy": selector_policy,
            "total_steps": len(timeline),
            "total_ios_dispatched": total_ios_dispatched,
            "total_bytes_dispatched": total_bytes_dispatched,
            "final_active_pg": current_active_pg_id,
            "final_queued_ios_count": len(queued_ios)
        },
        "path_statistics": path_states,
        "timeline_trace": trace
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
