import json
import heapq
import sys

def solve(input_data):
    pool_size = int(input_data.get("pool_size", 10))
    timeout_ms = int(input_data.get("connection_timeout_ms", 1000))
    tasks = input_data.get("tasks", [])

    available_connections = pool_size

    task_states = {}
    for t in tasks:
        tid = t["task_id"]
        depth = int(t.get("nested_depth", 1))
        p_dur = int(t.get("parent_duration_ms", 50))
        c_dur = int(t.get("child_duration_ms", 50)) if depth > 1 else 0
        arr = int(t.get("arrival_time_ms", 0))
        task_states[tid] = {
            "task_id": tid,
            "depth": depth,
            "arrival_time": arr,
            "p_dur": p_dur,
            "c_dur": c_dur,
            "held_connections": 0,
            "status": "WAITING_PARENT",
            "parent_acquired_at": None,
            "child_requested_at": None,
            "child_acquired_at": None,
            "child_released_at": None,
            "finished_at": None,
            "error": None
        }

    events = []
    for t in tasks:
        tid = t["task_id"]
        arr = task_states[tid]["arrival_time"]
        heapq.heappush(events, (arr, 1, 'ARRIVE', tid))

    waiters = []
    timed_out_tasks = []
    completed_tasks = []
    max_utilized = 0

    def try_allocate():
        nonlocal available_connections, max_utilized
        allocated = False
        while available_connections > 0 and waiters:
            tid, req_type, req_time = waiters.pop(0)
            st = task_states[tid]
            if st["status"] == "TIMED_OUT":
                continue
            
            available_connections -= 1
            st["held_connections"] += 1
            max_utilized = max(max_utilized, pool_size - available_connections)

            if req_type == 'PARENT':
                st["parent_acquired_at"] = current_time
                if st["depth"] == 1:
                    st["status"] = "RUNNING_SINGLE"
                    heapq.heappush(events, (current_time + st["p_dur"], 2, 'FINISH_SINGLE', tid))
                else:
                    st["status"] = "RUNNING_PARENT_1"
                    p1_dur = st["p_dur"] // 2
                    heapq.heappush(events, (current_time + p1_dur, 2, 'FINISH_PARENT_1', tid))
            elif req_type == 'CHILD':
                st["child_acquired_at"] = current_time
                st["status"] = "RUNNING_CHILD"
                heapq.heappush(events, (current_time + st["c_dur"], 2, 'FINISH_CHILD', tid))
            
            allocated = True
        return allocated

    current_time = 0

    while events:
        evt_time, priority, evt_type, tid = heapq.heappop(events)
        current_time = evt_time
        st = task_states.get(tid)

        if evt_type == 'ARRIVE':
            st["status"] = "WAITING_PARENT"
            waiters.append((tid, 'PARENT', current_time))
            heapq.heappush(events, (current_time + timeout_ms, 3, 'TIMEOUT', (tid, 'PARENT', current_time)))
            try_allocate()

        elif evt_type == 'FINISH_PARENT_1':
            if st["status"] != "RUNNING_PARENT_1":
                continue
            st["status"] = "WAITING_CHILD"
            st["child_requested_at"] = current_time
            waiters.append((tid, 'CHILD', current_time))
            heapq.heappush(events, (current_time + timeout_ms, 3, 'TIMEOUT', (tid, 'CHILD', current_time)))
            try_allocate()

        elif evt_type == 'FINISH_CHILD':
            if st["status"] != "RUNNING_CHILD":
                continue
            available_connections += 1
            st["held_connections"] -= 1
            st["child_released_at"] = current_time
            st["status"] = "RUNNING_PARENT_2"
            p2_dur = st["p_dur"] - (st["p_dur"] // 2)
            heapq.heappush(events, (current_time + p2_dur, 2, 'FINISH_PARENT_2', tid))
            try_allocate()

        elif evt_type == 'FINISH_PARENT_2':
            if st["status"] != "RUNNING_PARENT_2":
                continue
            available_connections += 1
            st["held_connections"] -= 1
            st["status"] = "COMPLETED"
            st["finished_at"] = current_time
            completed_tasks.append(tid)
            try_allocate()

        elif evt_type == 'FINISH_SINGLE':
            if st["status"] != "RUNNING_SINGLE":
                continue
            available_connections += 1
            st["held_connections"] -= 1
            st["status"] = "COMPLETED"
            st["finished_at"] = current_time
            completed_tasks.append(tid)
            try_allocate()

        elif evt_type == 'TIMEOUT':
            target_tid, req_type, req_time = tid
            tgt_st = task_states[target_tid]
            is_waiting = False
            if req_type == 'PARENT' and tgt_st["status"] == "WAITING_PARENT":
                is_waiting = True
            elif req_type == 'CHILD' and tgt_st["status"] == "WAITING_CHILD" and tgt_st["child_requested_at"] == req_time:
                is_waiting = True

            if is_waiting:
                tgt_st["status"] = "TIMED_OUT"
                tgt_st["finished_at"] = current_time
                tgt_st["error"] = f"ConnectionTimeoutException: Connection not available within {timeout_ms}ms"
                timed_out_tasks.append(target_tid)
                if tgt_st["held_connections"] > 0:
                    available_connections += tgt_st["held_connections"]
                    tgt_st["held_connections"] = 0
                    try_allocate()

    max_concurrent_threads = len(tasks)
    max_conns_per_thread = max([t.get("nested_depth", 1) for t in tasks]) if tasks else 1
    safe_pool_size = max_concurrent_threads * (max_conns_per_thread - 1) + 1

    deadlock_detected = (len(timed_out_tasks) > 0 and pool_size < safe_pool_size and max_conns_per_thread > 1)
    
    if deadlock_detected:
        verdict = "CONNECTION_POOL_DEADLOCK_COLLAPSE"
        diag = (f"CRITICAL: HikariCP connection pool starvation deadlock detected! "
                f"{len(timed_out_tasks)} threads timed out waiting for child connections. "
                f"Formula Pool Size >= T * (C - 1) + 1 requires at least {safe_pool_size} connections, "
                f"but pool size is only {pool_size}.")
    elif len(timed_out_tasks) > 0:
        verdict = "CONNECTION_TIMEOUT_CONGESTION"
        diag = f"WARNING: Connection timeout occurred due to high traffic congestion ({len(timed_out_tasks)} tasks timed out)."
    else:
        verdict = "OPTIMAL_POOL_EXECUTION"
        diag = f"SUCCESS: All {len(completed_tasks)} tasks completed with zero pool starvation deadlocks."

    task_results = []
    for t in tasks:
        tid = t["task_id"]
        st = task_states[tid]
        task_results.append({
            "task_id": tid,
            "status": st["status"],
            "parent_acquired_at": st["parent_acquired_at"],
            "child_requested_at": st["child_requested_at"],
            "child_acquired_at": st["child_acquired_at"],
            "finished_at": st["finished_at"],
            "error": st["error"]
        })

    return {
        "summary": {
            "total_tasks": len(tasks),
            "completed_tasks": len(completed_tasks),
            "failed_tasks": len(timed_out_tasks),
            "deadlock_detected": deadlock_detected,
            "timed_out_tasks": timed_out_tasks,
            "max_pool_utilization": max_utilized,
            "safe_pool_size_calculated": safe_pool_size,
            "overall_verdict": verdict
        },
        "tasks": task_results,
        "diagnosis": diag
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
