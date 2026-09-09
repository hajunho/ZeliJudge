import heapq
import json
import sys

def solve(data):
    tomcat_max_threads = data.get("tomcat_max_threads", 200)
    tomcat_queue_capacity = data.get("tomcat_queue_capacity", 100)
    
    hikaricp_pool_size = data.get("hikaricp_pool_size", 20)
    hikaricp_timeout_ms = data.get("hikaricp_connection_timeout_ms", 500)
    
    requests = data.get("requests", [])
    requests = sorted(requests, key=lambda x: x.get("timestamp_ms", 0))
    
    active_threads = 0
    peak_active_threads = 0
    
    tomcat_queue = []
    peak_tomcat_queue = 0
    
    hikari_active = 0
    peak_hikari_active = 0
    hikari_wait_queue = []
    
    completed_requests = 0
    rejected_queue_full = 0
    rejected_db_timeout = 0
    
    req_results = {}
    
    event_queue = []
    seq = 0
    for r in requests:
        seq += 1
        heapq.heappush(event_queue, (r["timestamp_ms"], seq, "REQ_ARRIVE", r))
        
    while event_queue:
        event_time, _, ev_type, ev_data = heapq.heappop(event_queue)
        
        if ev_type == "QUERY_FINISH":
            hikari_active -= 1
            active_threads -= 1
            r_id = ev_data["request_id"]
            req_results[r_id] = {
                "request_id": r_id,
                "status": "SUCCESS",
                "finish_time_ms": event_time
            }
            completed_requests += 1
            
            # 1. Someone waiting for DB connection?
            while hikari_wait_queue and hikari_active < hikaricp_pool_size:
                wait_start, wait_req = hikari_wait_queue.pop(0)
                if event_time - wait_start > hikaricp_timeout_ms:
                    rejected_db_timeout += 1
                    active_threads -= 1
                    req_results[wait_req["request_id"]] = {
                        "request_id": wait_req["request_id"],
                        "status": "DB_CONNECTION_TIMEOUT_504",
                        "finish_time_ms": wait_start + hikaricp_timeout_ms
                    }
                else:
                    hikari_active += 1
                    peak_hikari_active = max(peak_hikari_active, hikari_active)
                    q_dur = wait_req.get("query_duration_ms", 10)
                    finish_t = event_time + q_dur
                    seq += 1
                    heapq.heappush(event_queue, (finish_t, seq, "QUERY_FINISH", wait_req))
                    break
                    
            # 2. Check if tomcat queue has pending requests and threads available
            while tomcat_queue and active_threads < tomcat_max_threads:
                queued_req = tomcat_queue.pop(0)
                active_threads += 1
                peak_active_threads = max(peak_active_threads, active_threads)
                if hikari_active < hikaricp_pool_size:
                    hikari_active += 1
                    peak_hikari_active = max(peak_hikari_active, hikari_active)
                    q_dur = queued_req.get("query_duration_ms", 10)
                    seq += 1
                    heapq.heappush(event_queue, (event_time + q_dur, seq, "QUERY_FINISH", queued_req))
                else:
                    hikari_wait_queue.append((event_time, queued_req))
                    
        elif ev_type == "REQ_ARRIVE":
            req = ev_data
            r_id = req["request_id"]
            
            if active_threads < tomcat_max_threads:
                active_threads += 1
                peak_active_threads = max(peak_active_threads, active_threads)
                
                if hikari_active < hikaricp_pool_size:
                    hikari_active += 1
                    peak_hikari_active = max(peak_hikari_active, hikari_active)
                    q_dur = req.get("query_duration_ms", 10)
                    finish_t = event_time + q_dur
                    seq += 1
                    heapq.heappush(event_queue, (finish_t, seq, "QUERY_FINISH", req))
                else:
                    hikari_wait_queue.append((event_time, req))
            else:
                if len(tomcat_queue) < tomcat_queue_capacity:
                    tomcat_queue.append(req)
                    peak_tomcat_queue = max(peak_tomcat_queue, len(tomcat_queue))
                else:
                    rejected_queue_full += 1
                    req_results[r_id] = {
                        "request_id": r_id,
                        "status": "TOMCAT_QUEUE_FULL_503",
                        "finish_time_ms": event_time
                    }
                    
    # Drain remaining in wait queue
    while hikari_wait_queue:
        wait_start, wait_req = hikari_wait_queue.pop(0)
        rejected_db_timeout += 1
        req_results[wait_req["request_id"]] = {
            "request_id": wait_req["request_id"],
            "status": "DB_CONNECTION_TIMEOUT_504",
            "finish_time_ms": wait_start + hikaricp_timeout_ms
        }
        
    while tomcat_queue:
        q_req = tomcat_queue.pop(0)
        rejected_queue_full += 1
        req_results[q_req["request_id"]] = {
            "request_id": q_req["request_id"],
            "status": "TOMCAT_QUEUE_TIMEOUT_503",
            "finish_time_ms": event_time
        }
        
    thread_stack_memory_mb = peak_active_threads * 1
    
    if rejected_db_timeout > 0:
        if peak_active_threads >= 500:
            verdict = "THREAD_POOL_SATURATION_CASCADE_FAILURE"
        else:
            verdict = "DB_BOTTLENECK_QUEUE_EXHAUSTION"
    elif rejected_queue_full > 0:
        verdict = "TOMCAT_QUEUE_OVERFLOW_FAST_FAIL"
    else:
        verdict = "BALANCED_OPTIMAL_THROUGHPUT"
        
    summary = {
        "tomcat_max_threads": tomcat_max_threads,
        "tomcat_queue_capacity": tomcat_queue_capacity,
        "hikaricp_pool_size": hikaricp_pool_size,
        "total_requests": len(requests),
        "completed_requests": completed_requests,
        "rejected_queue_full": rejected_queue_full,
        "rejected_db_timeout": rejected_db_timeout,
        "peak_active_threads": peak_active_threads,
        "peak_tomcat_queue": peak_tomcat_queue,
        "peak_hikari_active": peak_hikari_active,
        "thread_stack_memory_mb": thread_stack_memory_mb,
        "overall_verdict": verdict
    }
    
    ordered_results = [req_results.get(r["request_id"], {"request_id": r["request_id"], "status": "UNKNOWN"}) for r in requests]
    
    return {
        "summary": summary,
        "sample_results": ordered_results[:10]
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            sys.exit(0)
        input_data = json.loads(raw_input)
        result = solve(input_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
