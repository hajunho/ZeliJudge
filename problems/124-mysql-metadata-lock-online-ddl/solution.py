import sys
import json
import math

def simulate_metadata_lock(data):
    mode = data.get("mode", "NAIVE_DDL")
    config = data.get("config", {})
    max_connections = config.get("max_connections", 10)
    lock_wait_timeout = config.get("lock_wait_timeout", 5)
    chunk_size = config.get("chunk_size", 100)
    
    initial_rows = data.get("initial_rows", 100)
    timeline = data.get("timeline", [])
    
    current_rows = initial_rows
    schema_version = 1
    
    active_connections = 0
    max_connections_used = 0
    
    # MDL Lock state
    shared_holders = set()  # set of tx_ids holding SHARED lock
    exclusive_holder = None # tx_id holding EXCLUSIVE lock or None
    wait_queue = []         # FIFO queue of waiting items
    
    # Running transactions: list of dicts
    running_txs = []
    
    # Results dictionary keyed by tx_id
    results = {}
    
    # Events grouped by time
    events_by_time = {}
    for ev in timeline:
        events_by_time.setdefault(ev["time"], []).append(ev)
        
    current_time = 0
    ghost_state = None
    
    all_times = [ev["time"] for ev in timeline]
    max_input_time = max(all_times) if all_times else 0
    
    def try_promote(t):
        nonlocal exclusive_holder
        if exclusive_holder is not None:
            return
            
        if not wait_queue:
            return
            
        if wait_queue[0]["lock_type"] == "EXCLUSIVE":
            if len(shared_holders) == 0:
                item = wait_queue.pop(0)
                exclusive_holder = item["tx_id"]
                running_txs.append({
                    "tx_id": item["tx_id"],
                    "action": item["action"],
                    "lock_type": "EXCLUSIVE",
                    "start_time": t,
                    "finish_time": t + item["duration"],
                    "row_delta": item.get("row_delta", 0)
                })
        elif wait_queue[0]["lock_type"] == "SHARED":
            while wait_queue and wait_queue[0]["lock_type"] == "SHARED":
                item = wait_queue.pop(0)
                shared_holders.add(item["tx_id"])
                running_txs.append({
                    "tx_id": item["tx_id"],
                    "action": item["action"],
                    "lock_type": "SHARED",
                    "start_time": t,
                    "finish_time": t + item["duration"],
                    "row_delta": item.get("row_delta", 0)
                })
                
    while True:
        max_connections_used = max(max_connections_used, active_connections)
        
        # 1. Complete active transactions finishing at current_time
        completed = [tx for tx in running_txs if tx["finish_time"] <= current_time]
        running_txs = [tx for tx in running_txs if tx["finish_time"] > current_time]
        
        for tx in completed:
            active_connections -= 1
            if tx["lock_type"] == "EXCLUSIVE":
                exclusive_holder = None
                schema_version = 2
            elif tx["lock_type"] == "SHARED":
                shared_holders.discard(tx["tx_id"])
                
            current_rows += tx.get("row_delta", 0)
            results[tx["tx_id"]] = {
                "tx_id": tx["tx_id"],
                "action": tx["action"],
                "status": "COMMITTED",
                "start_time": tx["start_time"],
                "finish_time": current_time
            }
            
        # Check ghost completion
        if ghost_state and ghost_state["finish_time"] <= current_time:
            active_connections -= 1
            schema_version = 2
            results[ghost_state["tx_id"]] = {
                "tx_id": ghost_state["tx_id"],
                "action": "ALTER_TABLE",
                "status": "COMMITTED",
                "start_time": ghost_state["start_time"],
                "finish_time": current_time
            }
            ghost_state = None
            
        # 2. Try promoting waiters from queue
        try_promote(current_time)
        
        # 3. Check lock wait timeouts for items still in wait_queue
        timed_out = []
        rem_queue = []
        for item in wait_queue:
            if lock_wait_timeout > 0 and (current_time - item["enqueue_time"]) >= lock_wait_timeout:
                timed_out.append(item)
            else:
                rem_queue.append(item)
        wait_queue = rem_queue
        
        for item in timed_out:
            active_connections -= 1
            results[item["tx_id"]] = {
                "tx_id": item["tx_id"],
                "action": item["action"],
                "status": "LOCK_WAIT_TIMEOUT",
                "start_time": None,
                "finish_time": current_time
            }
            
        # If any waiter timed out, try promoting again (queue head might have changed)
        if timed_out:
            try_promote(current_time)
            
        # 4. Process incoming events at current_time
        events = events_by_time.get(current_time, [])
        for ev in events:
            tx_id = ev["tx_id"]
            action = ev["action"]
            duration = ev.get("duration", 1)
            row_delta = ev.get("row_delta", 0)
            if action == "USER_QUERY" and "row_delta" not in ev:
                qtype = ev.get("type", "SELECT")
                if qtype == "INSERT":
                    row_delta = 1
                elif qtype == "DELETE":
                    row_delta = -1
                else:
                    row_delta = 0
                    
            if active_connections >= max_connections:
                results[tx_id] = {
                    "tx_id": tx_id,
                    "action": action,
                    "status": "CONNECTION_POOL_EXHAUSTED",
                    "start_time": None,
                    "finish_time": current_time
                }
                continue
                
            active_connections += 1
            max_connections_used = max(max_connections_used, active_connections)
            
            if mode == "GHOST_DDL" and action == "ALTER_TABLE":
                chunks = max(1, math.ceil(current_rows / chunk_size))
                ghost_state = {
                    "tx_id": tx_id,
                    "start_time": current_time,
                    "finish_time": current_time + chunks + 1
                }
            elif action == "ALTER_TABLE":
                # NAIVE_DDL requires EXCLUSIVE lock
                if exclusive_holder is None and len(shared_holders) == 0 and len(wait_queue) == 0:
                    exclusive_holder = tx_id
                    running_txs.append({
                        "tx_id": tx_id,
                        "action": action,
                        "lock_type": "EXCLUSIVE",
                        "start_time": current_time,
                        "finish_time": current_time + duration,
                        "row_delta": 0
                    })
                else:
                    wait_queue.append({
                        "tx_id": tx_id,
                        "action": action,
                        "lock_type": "EXCLUSIVE",
                        "duration": duration,
                        "row_delta": 0,
                        "enqueue_time": current_time
                    })
            else:
                # USER_QUERY or START_LONG_TX -> requires SHARED lock
                has_exclusive_in_queue = any(x["lock_type"] == "EXCLUSIVE" for x in wait_queue)
                if exclusive_holder is None and not has_exclusive_in_queue and len(wait_queue) == 0:
                    shared_holders.add(tx_id)
                    running_txs.append({
                        "tx_id": tx_id,
                        "action": action,
                        "lock_type": "SHARED",
                        "start_time": current_time,
                        "finish_time": current_time + duration,
                        "row_delta": row_delta
                    })
                else:
                    wait_queue.append({
                        "tx_id": tx_id,
                        "action": action,
                        "lock_type": "SHARED",
                        "duration": duration,
                        "row_delta": row_delta,
                        "enqueue_time": current_time
                    })
                    
        # Check termination
        if current_time >= max_input_time and not running_txs and not wait_queue and not ghost_state:
            break
            
        current_time += 1
        
    query_results = []
    seen = set()
    for ev in timeline:
        tx_id = ev["tx_id"]
        if tx_id in results and tx_id not in seen:
            query_results.append(results[tx_id])
            seen.add(tx_id)
            
    summary = {
        "total_requests": len(query_results),
        "committed": sum(1 for r in query_results if r["status"] == "COMMITTED"),
        "lock_wait_timeouts": sum(1 for r in query_results if r["status"] == "LOCK_WAIT_TIMEOUT"),
        "connection_pool_exhaustions": sum(1 for r in query_results if r["status"] == "CONNECTION_POOL_EXHAUSTED"),
        "max_concurrent_connections_used": max_connections_used,
        "final_rows": current_rows,
        "schema_version": schema_version
    }
    
    return {
        "mode": mode,
        "summary": summary,
        "query_results": query_results
    }

def main():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return
    data = json.loads(input_data)
    result = simulate_metadata_lock(data)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
