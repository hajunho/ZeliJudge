import sys
import json
import heapq
import copy

def simulate_nginx_keepalive_pool(data):
    data = copy.deepcopy(data)
    nginx_cfg = data.get("nginx_config", {})
    net_cfg = data.get("network_config", {})
    traffic = data.get("traffic", [])
    
    http_version = str(nginx_cfg.get("proxy_http_version", "1.0"))
    conn_header = str(nginx_cfg.get("proxy_set_header_connection", "default"))
    pool_size = int(nginx_cfg.get("upstream_keepalive_pool_size", 32))
    keepalive_timeout = float(nginx_cfg.get("keepalive_timeout_sec", 60.0))
    keepalive_max_reqs = int(nginx_cfg.get("keepalive_requests", 100))
    
    hs_latency_sec = float(net_cfg.get("handshake_latency_ms", 10.0)) / 1000.0
    port_range = net_cfg.get("ephemeral_port_range", {"min": 32768, "max": 60999})
    total_ports = int(port_range.get("max", 60999)) - int(port_range.get("min", 32768)) + 1
    tw_duration = float(net_cfg.get("time_wait_duration_sec", 60.0))
    
    # Check if keepalive is active
    # In Nginx: must be HTTP/1.1 AND Connection header cleared ("empty")
    keepalive_active = (http_version == "1.1" and conn_header == "empty" and pool_size > 0)
    
    idle_pool = []
    time_wait_heap = []
    
    next_conn_id = 1
    allocated_ports = 0
    
    reused_count = 0
    new_conns_created = 0
    failed_requests = 0
    successful_requests = 0
    
    peak_tw_sockets = 0
    peak_open_sockets = 0
    
    total_latency_ms = 0.0
    request_results = []
    
    traffic_sorted = sorted(traffic, key=lambda r: float(r.get("time", 0.0)))
    
    event_seq = 0
    event_queue = []
    for req in traffic_sorted:
        event_seq += 1
        heapq.heappush(event_queue, (float(req.get("time", 0.0)), 1, event_seq, "REQ", req))
        
    current_time = 0.0
    
    while event_queue:
        t, ev_prio, seq, ev_type, ev_data = heapq.heappop(event_queue)
        current_time = t
        
        while time_wait_heap and time_wait_heap[0] <= current_time:
            heapq.heappop(time_wait_heap)
            allocated_ports -= 1
            
        if ev_type == "TW_EXPIRE":
            continue
            
        elif ev_type == "REQ_FINISH":
            conn = ev_data
            if keepalive_active:
                if conn["requests_served"] >= keepalive_max_reqs:
                    tw_end = current_time + tw_duration
                    heapq.heappush(time_wait_heap, tw_end)
                    event_seq += 1
                    heapq.heappush(event_queue, (tw_end, 0, event_seq, "TW_EXPIRE", None))
                else:
                    valid_idle = []
                    for c in idle_pool:
                        if current_time - c["last_used_time"] > keepalive_timeout:
                            tw_end = current_time + tw_duration
                            heapq.heappush(time_wait_heap, tw_end)
                            event_seq += 1
                            heapq.heappush(event_queue, (tw_end, 0, event_seq, "TW_EXPIRE", None))
                        else:
                            valid_idle.append(c)
                    idle_pool = valid_idle
                    
                    if len(idle_pool) >= pool_size:
                        oldest = idle_pool.pop(0)
                        tw_end = current_time + tw_duration
                        heapq.heappush(time_wait_heap, tw_end)
                        event_seq += 1
                        heapq.heappush(event_queue, (tw_end, 0, event_seq, "TW_EXPIRE", None))
                        
                    conn["last_used_time"] = current_time
                    idle_pool.append(conn)
            else:
                tw_end = current_time + tw_duration
                heapq.heappush(time_wait_heap, tw_end)
                event_seq += 1
                heapq.heappush(event_queue, (tw_end, 0, event_seq, "TW_EXPIRE", None))
                
        elif ev_type == "REQ":
            req = ev_data
            req_id = req.get("request_id")
            dur_ms = float(req.get("duration_ms", 20.0))
            
            if keepalive_active:
                valid_idle = []
                for c in idle_pool:
                    if current_time - c["last_used_time"] > keepalive_timeout:
                        tw_end = current_time + tw_duration
                        heapq.heappush(time_wait_heap, tw_end)
                        event_seq += 1
                        heapq.heappush(event_queue, (tw_end, 0, event_seq, "TW_EXPIRE", None))
                    else:
                        valid_idle.append(c)
                idle_pool = valid_idle
                
            conn_to_use = None
            is_reused = False
            
            if keepalive_active and idle_pool:
                conn_to_use = idle_pool.pop()
                conn_to_use["requests_served"] += 1
                is_reused = True
                reused_count += 1
                actual_hs_ms = 0.0
            else:
                if allocated_ports >= total_ports:
                    failed_requests += 1
                    request_results.append({
                        "request_id": req_id,
                        "time": round(current_time, 3),
                        "status": "FAILED",
                        "error": "ERR_EPHEMERAL_PORT_EXHAUSTION",
                        "is_reused": False,
                        "latency_ms": 0.0
                    })
                    continue
                    
                allocated_ports += 1
                conn_to_use = {
                    "conn_id": next_conn_id,
                    "requests_served": 1,
                    "last_used_time": current_time
                }
                next_conn_id += 1
                new_conns_created += 1
                actual_hs_ms = hs_latency_sec * 1000.0
                
            successful_requests += 1
            req_latency_ms = round(actual_hs_ms + dur_ms, 2)
            total_latency_ms += req_latency_ms
            finish_time = current_time + (req_latency_ms / 1000.0)
            
            request_results.append({
                "request_id": req_id,
                "time": round(current_time, 3),
                "status": "SUCCESS",
                "error": None,
                "is_reused": is_reused,
                "latency_ms": req_latency_ms
            })
            
            event_seq += 1
            heapq.heappush(event_queue, (finish_time, 0, event_seq, "REQ_FINISH", conn_to_use))
            
        current_tw = len(time_wait_heap)
        current_open = allocated_ports
        if current_tw > peak_tw_sockets:
            peak_tw_sockets = current_tw
        if current_open > peak_open_sockets:
            peak_open_sockets = current_open
            
    total_reqs = len(traffic)
    reuse_ratio = round((reused_count / total_reqs * 100.0) if total_reqs > 0 else 0.0, 2)
    avg_latency = round((total_latency_ms / successful_requests) if successful_requests > 0 else 0.0, 2)
    
    summary = {
        "keepalive_active": keepalive_active,
        "total_requests": total_reqs,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "connection_reuse_ratio_pct": reuse_ratio,
        "new_connections_created": new_conns_created,
        "peak_time_wait_sockets": peak_tw_sockets,
        "peak_allocated_ports": peak_open_sockets,
        "average_latency_ms": avg_latency
    }
    
    return {
        "summary": summary,
        "requests": request_results
    }

def main():
    input_text = sys.stdin.read().strip()
    if not input_text:
        return
    data = json.loads(input_text)
    out = simulate_nginx_keepalive_pool(data)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
