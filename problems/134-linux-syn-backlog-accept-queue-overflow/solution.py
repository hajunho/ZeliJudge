import json
import sys

def solve(data):
    somaxconn = data.get("somaxconn", 128)
    tcp_max_syn_backlog = data.get("tcp_max_syn_backlog", 128)
    tcp_abort_on_overflow = data.get("tcp_abort_on_overflow", 0)
    tcp_syncookies = data.get("tcp_syncookies", 1)
    
    app_listen_backlog = data.get("app_listen_backlog", 128)
    accept_queue_limit = min(app_listen_backlog, somaxconn)
    
    accept_interval_ms = data.get("app_accept_interval_ms", 20)
    accept_batch_size = data.get("app_accept_batch_size", 10)
    
    attempts = data.get("connection_attempts", [])
    attempts = sorted(attempts, key=lambda x: x.get("syn_time_ms", 0))
    
    syn_queue = []
    accept_queue = []
    
    syn_drops = 0
    syn_cookie_used = 0
    accept_queue_overflows = 0
    rst_sent_count = 0
    syn_ack_retransmits = 0
    successful_connections = 0
    
    sim_events = []
    for att in attempts:
        cid = att["client_id"]
        syn_t = att.get("syn_time_ms", 0)
        rtt = att.get("rtt_ms", 10)
        sim_events.append({"time": syn_t, "type": "SYN_ARRIVE", "data": att})
        sim_events.append({"time": syn_t + rtt, "type": "ACK_ARRIVE", "client_id": cid, "att": att})
        
    max_time = max([e["time"] for e in sim_events]) + accept_interval_ms * 2 if sim_events else 100
    curr_accept_t = 0
    while curr_accept_t <= max_time:
        sim_events.append({"time": curr_accept_t, "type": "APP_ACCEPT"})
        curr_accept_t += accept_interval_ms
        
    sim_events.sort(key=lambda e: (e["time"], 0 if e["type"] == "APP_ACCEPT" else (1 if e["type"] == "ACK_ARRIVE" else 2)))
    
    client_state = {}
    peak_syn_queue = 0
    peak_accept_queue = 0
    
    for ev in sim_events:
        t = ev["time"]
        ev_type = ev["type"]
        
        if ev_type == "APP_ACCEPT":
            drained = 0
            while accept_queue and drained < accept_batch_size:
                conn = accept_queue.pop(0)
                client_state[conn["client_id"]]["status"] = "ACCEPTED"
                client_state[conn["client_id"]]["accepted_at_ms"] = t
                successful_connections += 1
                drained += 1
                
        elif ev_type == "SYN_ARRIVE":
            att = ev["data"]
            cid = att["client_id"]
            client_state[cid] = {"client_id": cid, "syn_time": t, "status": "SYN_RCVD"}
            
            if len(syn_queue) >= tcp_max_syn_backlog:
                if tcp_syncookies == 1:
                    syn_cookie_used += 1
                    client_state[cid]["syn_cookie"] = True
                else:
                    syn_drops += 1
                    client_state[cid]["status"] = "SYN_DROPPED_QUEUE_FULL"
                    continue
            else:
                syn_queue.append(cid)
                peak_syn_queue = max(peak_syn_queue, len(syn_queue))
                
        elif ev_type == "ACK_ARRIVE":
            cid = ev["client_id"]
            c_info = client_state.get(cid)
            if not c_info or c_info["status"] != "SYN_RCVD":
                continue
                
            if cid in syn_queue:
                syn_queue.remove(cid)
                
            if len(accept_queue) >= accept_queue_limit:
                accept_queue_overflows += 1
                if tcp_abort_on_overflow == 1:
                    rst_sent_count += 1
                    c_info["status"] = "ABORTED_WITH_RST"
                else:
                    syn_ack_retransmits += 1
                    c_info["status"] = "ACK_DROPPED_SYNACK_RETRANSMIT"
            else:
                accept_queue.append({"client_id": cid, "established_at_ms": t})
                peak_accept_queue = max(peak_accept_queue, len(accept_queue))
                c_info["status"] = "IN_ACCEPT_QUEUE"
                
    while accept_queue:
        conn = accept_queue.pop(0)
        client_state[conn["client_id"]]["status"] = "ACCEPTED"
        successful_connections += 1
        
    client_results = list(client_state.values())
    
    if accept_queue_overflows > 0:
        if tcp_abort_on_overflow == 1:
            verdict = "ACCEPT_QUEUE_OVERFLOW_RST_STORM"
        else:
            verdict = "ACCEPT_QUEUE_OVERFLOW_SILENT_DROP_STALL"
    elif syn_drops > 0:
        verdict = "SYN_QUEUE_EXHAUSTION_DROP"
    elif syn_cookie_used > 0:
        verdict = "SYN_FLOOD_MITIGATED_BY_COOKIES"
    else:
        verdict = "ALL_CONNECTIONS_HEALTHY"
        
    summary = {
        "somaxconn": somaxconn,
        "app_listen_backlog": app_listen_backlog,
        "effective_accept_queue_limit": accept_queue_limit,
        "tcp_max_syn_backlog": tcp_max_syn_backlog,
        "tcp_abort_on_overflow": tcp_abort_on_overflow,
        "tcp_syncookies": tcp_syncookies,
        "total_attempts": len(attempts),
        "successful_connections": successful_connections,
        "syn_drops": syn_drops,
        "syn_cookie_used": syn_cookie_used,
        "accept_queue_overflows": accept_queue_overflows,
        "syn_ack_retransmits": syn_ack_retransmits,
        "rst_sent_count": rst_sent_count,
        "peak_syn_queue": peak_syn_queue,
        "peak_accept_queue": peak_accept_queue,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "client_results_sample": client_results[:10]
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
