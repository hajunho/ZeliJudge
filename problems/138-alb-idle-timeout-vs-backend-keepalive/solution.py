import json
import sys

def solve(data):
    alb_idle_timeout_ms = data.get("alb_idle_timeout_ms", 60000)
    backend_keepalive_timeout_ms = data.get("backend_keepalive_timeout_ms", 60000)
    network_latency_ms = data.get("network_latency_ms", 2)
    
    requests = data.get("requests", [])
    requests = sorted(requests, key=lambda x: x.get("arrival_time_ms", 0))
    
    connections = []
    next_conn_id = 1
    
    total_requests = len(requests)
    successful_requests = 0
    failed_requests_502 = 0
    new_connections_created = 0
    reused_connections_count = 0
    alb_initiated_closes = 0
    backend_initiated_closes = 0
    race_condition_collisions = 0
    
    request_results = []
    
    for req in requests:
        req_id = req.get("request_id", "")
        arr_time = req.get("arrival_time_ms", 0)
        proc_time = req.get("processing_time_ms", 50)
        
        # 1. Update state of existing connections at arr_time
        for conn in connections:
            if conn["state"] == "BUSY" and conn["busy_until_time"] <= arr_time:
                conn["state"] = "IDLE"
                
            if conn["state"] == "IDLE":
                # Check if ALB closed it before arr_time
                if conn["alb_close_time"] <= arr_time:
                    conn["state"] = "CLOSED"
                    conn["closed_by"] = "ALB_IDLE_TIMEOUT"
                    alb_initiated_closes += 1
                # Check if Backend closed it and FIN reached ALB before arr_time
                elif conn["backend_fin_reach_alb_time"] <= arr_time:
                    conn["state"] = "CLOSED"
                    conn["closed_by"] = "BACKEND_FIN_RECEIVED"
                    backend_initiated_closes += 1
                    
        # 2. Find an IDLE connection in ALB pool
        chosen_conn = None
        for conn in connections:
            if conn["state"] == "IDLE":
                if arr_time - conn["last_activity_time"] < alb_idle_timeout_ms:
                    chosen_conn = conn
                    break
                    
        is_reused = False
        if chosen_conn is not None:
            is_reused = True
            reused_connections_count += 1
            target_conn = chosen_conn
        else:
            new_connections_created += 1
            target_conn = {
                "conn_id": next_conn_id,
                "state": "IDLE",
                "busy_until_time": 0,
                "last_activity_time": arr_time,
                "backend_close_time": arr_time + backend_keepalive_timeout_ms,
                "backend_fin_reach_alb_time": arr_time + backend_keepalive_timeout_ms + network_latency_ms,
                "alb_close_time": arr_time + alb_idle_timeout_ms
            }
            next_conn_id += 1
            connections.append(target_conn)
            
        # 3. ALB dispatches request on target_conn
        target_conn["state"] = "BUSY"
        req_reach_backend_time = arr_time + network_latency_ms
        completion_time = req_reach_backend_time + proc_time + network_latency_ms
        target_conn["busy_until_time"] = completion_time
        
        # Collision check
        collision = False
        if is_reused:
            if req_reach_backend_time > target_conn["backend_close_time"]:
                collision = True
                race_condition_collisions += 1
                failed_requests_502 += 1
                target_conn["state"] = "CLOSED"
                target_conn["closed_by"] = "RST_ON_CLOSED_SOCKET"
                request_results.append({
                    "request_id": req_id,
                    "connection_id": target_conn["conn_id"],
                    "status": "502_BAD_GATEWAY_RACE_CONDITION",
                    "reused": True,
                    "arrival_time_ms": arr_time,
                    "error_detail": f"Request reached backend at {req_reach_backend_time}ms after backend closed at {target_conn['backend_close_time']}ms"
                })
                continue
                
        # If no collision, request succeeds
        successful_requests += 1
        target_conn["last_activity_time"] = completion_time
        target_conn["backend_close_time"] = completion_time + backend_keepalive_timeout_ms
        target_conn["backend_fin_reach_alb_time"] = target_conn["backend_close_time"] + network_latency_ms
        target_conn["alb_close_time"] = completion_time + alb_idle_timeout_ms
        
        request_results.append({
            "request_id": req_id,
            "connection_id": target_conn["conn_id"],
            "status": "200_OK",
            "reused": is_reused,
            "arrival_time_ms": arr_time,
            "finish_time_ms": completion_time
        })
        
    timeout_diff = backend_keepalive_timeout_ms - alb_idle_timeout_ms
    
    if total_requests == 0:
        verdict = "NO_REQUESTS"
    elif failed_requests_502 > 0:
        verdict = "BACKEND_TIMEOUT_SHORTER_OR_EQUAL_502_RISK"
    elif timeout_diff > 0 and failed_requests_502 == 0:
        verdict = "OPTIMAL_BACKEND_TIMEOUT_PROTECTED"
    elif reused_connections_count == 0 and total_requests > 1:
        verdict = "ZERO_REUSE_SHORT_KEEPALIVE"
    else:
        verdict = "HEALTHY_NO_COLLISION"
        
    summary = {
        "alb_idle_timeout_ms": alb_idle_timeout_ms,
        "backend_keepalive_timeout_ms": backend_keepalive_timeout_ms,
        "timeout_difference_ms": timeout_diff,
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "failed_requests_502": failed_requests_502,
        "new_connections_created": new_connections_created,
        "reused_connections_count": reused_connections_count,
        "race_condition_collisions": race_condition_collisions,
        "alb_initiated_closes": alb_initiated_closes,
        "backend_initiated_closes": backend_initiated_closes,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "sample_results": request_results[:10]
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
