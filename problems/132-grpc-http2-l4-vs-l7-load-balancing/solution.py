import json
import sys

def solve(data):
    lb_type = data.get("load_balancer_type", "L4_PROXY")
    lb_policy = data.get("lb_policy", "ROUND_ROBIN")
    backend_servers = data.get("backend_servers", [])
    
    server_dict = {}
    for s in backend_servers:
        s_id = s["id"]
        server_dict[s_id] = {
            "max_capacity": s.get("max_capacity", 100),
            "is_healthy": s.get("is_healthy", True),
            "processed_count": 0,
            "rejected_count": 0,
            "active_concurrency": 0
        }
        
    all_server_ids = [s["id"] for s in backend_servers]
    
    clients = data.get("clients", [])
    requests = data.get("requests", [])
    max_connection_age_ms = data.get("max_connection_age_ms", None)
    
    # State tracking
    l4_rr_idx = 0
    client_tcp_conns = {} # client_id -> {"server_id": s_id, "created_at": ts, "reconnect_count": 0}
    l7_rr_idx = 0
    client_side_rr = {c["id"]: 0 for c in clients}
    
    active_requests = [] # list of (finish_time_ms, server_id, req_id)
    request_results = []
    
    for req in requests:
        req_id = req["request_id"]
        client_id = req["client_id"]
        req_time = req.get("timestamp_ms", 0)
        duration = req.get("duration_ms", 10)
        
        # Release finished requests up to req_time
        still_active = []
        for finish_time, s_id, r_id in active_requests:
            if finish_time <= req_time:
                server_dict[s_id]["active_concurrency"] -= 1
            else:
                still_active.append((finish_time, s_id, r_id))
        active_requests = still_active
        
        # Determine currently healthy servers
        healthy_server_ids = [s_id for s_id in all_server_ids if server_dict[s_id]["is_healthy"]]
        
        if not healthy_server_ids:
            request_results.append({
                "request_id": req_id,
                "client_id": client_id,
                "assigned_server": None,
                "status": "REJECTED_NO_HEALTHY_BACKEND",
                "routing_decision": "NO_HEALTHY_BACKEND"
            })
            continue
            
        assigned_server = None
        routing_decision_reason = ""
        
        if lb_type == "L4_PROXY":
            conn = client_tcp_conns.get(client_id)
            need_new_conn = False
            if conn is None:
                need_new_conn = True
            elif max_connection_age_ms and (req_time - conn["created_at"] >= max_connection_age_ms):
                need_new_conn = True
            elif conn["server_id"] not in healthy_server_ids:
                need_new_conn = True
                
            if need_new_conn:
                assigned_srv_id = healthy_server_ids[l4_rr_idx % len(healthy_server_ids)]
                l4_rr_idx += 1
                reconnect_count = (conn["reconnect_count"] + 1) if conn else 0
                client_tcp_conns[client_id] = {
                    "server_id": assigned_srv_id,
                    "created_at": req_time,
                    "reconnect_count": reconnect_count
                }
                conn = client_tcp_conns[client_id]
                routing_decision_reason = "L4_NEW_TCP_CONNECTION_PINNED" if reconnect_count == 0 else "L4_CONNECTION_AGE_RECONNECT"
            else:
                routing_decision_reason = "L4_MULTIPLEXED_ON_EXISTING_TCP"
                
            assigned_server = conn["server_id"]
            
        elif lb_type == "L7_PROXY":
            if lb_policy == "LEAST_CONCURRENT":
                # Pick healthy server with lowest active_concurrency
                min_conc = min(server_dict[s]["active_concurrency"] for s in healthy_server_ids)
                candidates = [s for s in healthy_server_ids if server_dict[s]["active_concurrency"] == min_conc]
                assigned_server = candidates[0]
                routing_decision_reason = "L7_LEAST_CONCURRENT_ROUTING"
            else: # ROUND_ROBIN
                assigned_server = healthy_server_ids[l7_rr_idx % len(healthy_server_ids)]
                l7_rr_idx += 1
                routing_decision_reason = "L7_STREAM_LEVEL_ROUND_ROBIN"
                
        elif lb_type == "CLIENT_SIDE":
            if client_id not in client_side_rr:
                client_side_rr[client_id] = 0
                
            if lb_policy == "LEAST_CONCURRENT":
                min_conc = min(server_dict[s]["active_concurrency"] for s in healthy_server_ids)
                candidates = [s for s in healthy_server_ids if server_dict[s]["active_concurrency"] == min_conc]
                assigned_server = candidates[0]
                routing_decision_reason = "CLIENT_SUBCHANNEL_LEAST_CONCURRENT"
            else: # ROUND_ROBIN
                curr_idx = client_side_rr[client_id]
                assigned_server = healthy_server_ids[curr_idx % len(healthy_server_ids)]
                client_side_rr[client_id] = curr_idx + 1
                routing_decision_reason = "CLIENT_SUBCHANNEL_ROUND_ROBIN"
                
        # Check capacity on assigned server
        s_info = server_dict[assigned_server]
        status = "PROCESSED"
        if s_info["active_concurrency"] >= s_info["max_capacity"]:
            status = "REJECTED_OVERLOADED"
            s_info["rejected_count"] += 1
        else:
            s_info["active_concurrency"] += 1
            s_info["processed_count"] += 1
            active_requests.append((req_time + duration, assigned_server, req_id))
            
        request_results.append({
            "request_id": req_id,
            "client_id": client_id,
            "assigned_server": assigned_server,
            "status": status,
            "routing_decision": routing_decision_reason
        })
        
    # Drain remaining active requests
    for finish_time, s_id, r_id in active_requests:
        server_dict[s_id]["active_concurrency"] -= 1
        
    server_stats = {}
    for s_id in all_server_ids:
        s = server_dict[s_id]
        server_stats[s_id] = {
            "processed": s["processed_count"],
            "rejected": s["rejected_count"],
            "total_received": s["processed_count"] + s["rejected_count"]
        }
        
    total_processed = sum(s["processed"] for s in server_stats.values())
    total_rejected = sum(s["rejected"] for s in server_stats.values()) + sum(1 for r in request_results if r["status"] == "REJECTED_NO_HEALTHY_BACKEND")
    
    total_received_list = [s["total_received"] for s in server_stats.values()]
    max_received = max(total_received_list) if total_received_list else 0
    min_received = min(total_received_list) if total_received_list else 0
    avg_received = sum(total_received_list) / len(total_received_list) if total_received_list else 1
    imbalance_ratio = round((max_received - min_received) / max(avg_received, 1.0), 2)
    
    verdict = "BALANCED"
    if total_rejected > 0:
        verdict = "SERVER_OVERLOAD_HOTSPOT_FAILURE"
    elif imbalance_ratio >= 1.0:
        verdict = "SEVERE_LOAD_IMBALANCE"
    elif imbalance_ratio >= 0.5:
        verdict = "MODERATE_LOAD_IMBALANCE"
        
    return {
        "summary": {
            "load_balancer_type": lb_type,
            "lb_policy": lb_policy,
            "total_requests": len(requests),
            "total_processed": total_processed,
            "total_rejected": total_rejected,
            "imbalance_ratio": imbalance_ratio,
            "overall_verdict": verdict
        },
        "server_stats": server_stats,
        "request_results": request_results
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
