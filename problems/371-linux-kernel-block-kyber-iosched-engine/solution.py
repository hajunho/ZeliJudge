import sys
import json
import math

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    target_read_lat_us = input_data.get("target_read_lat_us", 2000)
    target_sync_write_lat_us = input_data.get("target_sync_write_lat_us", 10000)
    max_async_depth = input_data.get("max_async_depth", 16)
    initial_async_depth = input_data.get("initial_async_depth", 8)
    sample_window_reqs = input_data.get("sample_window_reqs", 8)
    operations = input_data.get("operations", [])
    
    current_async_depth = initial_async_depth
    active_async_tokens = current_async_depth
    
    read_queue = []
    async_queue = []
    current_window_read_lats = []
    
    stats = {
        "reads_dispatched": 0,
        "asyncs_dispatched": 0,
        "asyncs_throttled": 0,
        "window_adjustments": 0,
        "scale_downs": 0,
        "scale_ups": 0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "SUBMIT_BIO":
            bio_id = op["bio_id"]
            bio_type = op.get("type", "READ").upper()
            
            if bio_type == "READ":
                read_queue.append(bio_id)
                op_log.append({
                    "op": "SUBMIT_BIO",
                    "bio_id": bio_id,
                    "type": "READ",
                    "status": "QUEUED_READ"
                })
            else:
                async_queue.append(bio_id)
                op_log.append({
                    "op": "SUBMIT_BIO",
                    "bio_id": bio_id,
                    "type": "ASYNC",
                    "status": "QUEUED_ASYNC"
                })
                
        elif op_type == "DISPATCH":
            dispatched = []
            while read_queue:
                r_id = read_queue.pop(0)
                stats["reads_dispatched"] += 1
                dispatched.append({"bio_id": r_id, "type": "READ"})
                
            while async_queue and active_async_tokens > 0:
                a_id = async_queue.pop(0)
                stats["asyncs_dispatched"] += 1
                active_async_tokens -= 1
                dispatched.append({"bio_id": a_id, "type": "ASYNC"})
                
            if async_queue and active_async_tokens == 0:
                stats["asyncs_throttled"] += len(async_queue)
                
            op_log.append({
                "op": "DISPATCH",
                "dispatched_count": len(dispatched),
                "dispatched_items": dispatched,
                "remaining_read_queue": len(read_queue),
                "remaining_async_queue": len(async_queue),
                "remaining_async_tokens": active_async_tokens
            })
            
        elif op_type == "COMPLETE_BIO":
            bio_id = op["bio_id"]
            bio_type = op.get("type", "READ").upper()
            lat_us = op.get("latency_us", 1000)
            
            if bio_type == "READ":
                current_window_read_lats.append(lat_us)
                
            if bio_type == "ASYNC":
                active_async_tokens = min(current_async_depth, active_async_tokens + 1)
                
            window_evaluated = False
            adjustment = "NONE"
            if len(current_window_read_lats) >= sample_window_reqs:
                stats["window_adjustments"] += 1
                window_evaluated = True
                
                sorted_lats = sorted(current_window_read_lats)
                p99_idx = int(math.ceil(len(sorted_lats) * 0.99)) - 1
                p99_lat = sorted_lats[p99_idx]
                
                if p99_lat > target_read_lat_us:
                    stats["scale_downs"] += 1
                    current_async_depth = max(1, current_async_depth // 2)
                    adjustment = "THROTTLE_SCALE_DOWN"
                else:
                    stats["scale_ups"] += 1
                    current_async_depth = min(max_async_depth, current_async_depth + 1)
                    adjustment = "EXPAND_SCALE_UP"
                    
                active_async_tokens = min(current_async_depth, active_async_tokens)
                current_window_read_lats = []
                
            op_log.append({
                "op": "COMPLETE_BIO",
                "bio_id": bio_id,
                "type": bio_type,
                "latency_us": lat_us,
                "window_evaluated": window_evaluated,
                "adjustment": adjustment,
                "new_async_depth": current_async_depth,
                "active_async_tokens": active_async_tokens
            })

    res = {
        "target_read_lat_us": target_read_lat_us,
        "target_sync_write_lat_us": target_sync_write_lat_us,
        "max_async_depth": max_async_depth,
        "final_state": {
            "current_async_depth": current_async_depth,
            "active_async_tokens": active_async_tokens,
            "pending_reads": len(read_queue),
            "pending_asyncs": len(async_queue)
        },
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
