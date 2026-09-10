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
    tsq_limit_bytes = int(config.get("tsq_limit_bytes", 131072))
    bql_limit_bytes = int(config.get("bql_limit_bytes", 65536))
    mss = int(config.get("mss", 1460))
    skb_truesize = int(config.get("skb_truesize", 2048))
    nic_rate_bps = int(config.get("nic_rate_bps", 125000000))
    
    sockets_input = payload.get("sockets", [])
    operations = payload.get("operations", [])
    
    sockets = {}
    for s in sockets_input:
        sid = s["id"]
        sockets[sid] = {
            "id": sid,
            "pacing_rate_bps": int(s.get("pacing_rate_bps", 50000000)),
            "send_buffer": int(s.get("initial_send_buffer", 0)),
            "wmem_alloc": 0,
            "tsq_throttled": False,
            "pacing_next_ns": 0,
            "throttle_start_ns": None,
            "total_throttle_duration_ns": 0,
            "throttle_count": 0,
            "packets_sent": 0,
            "bytes_sent": 0
        }
        
    current_time_ns = 0
    nic_busy_until_ns = 0
    nic_in_flight_bytes = 0
    nic_queue = [] # list of {"sock_id": sid, "bytes": b, "truesize": ts, "complete_ns": t}
    log_events = []
    
    def process_nic_completions(upto_time_ns):
        nonlocal nic_in_flight_bytes
        while nic_queue and nic_queue[0]["complete_ns"] <= upto_time_ns:
            item = nic_queue.pop(0)
            sid = item["sock_id"]
            ts = item["truesize"]
            nic_in_flight_bytes = max(0, nic_in_flight_bytes - item["bytes"])
            
            if sid in sockets:
                sock = sockets[sid]
                sock["wmem_alloc"] = max(0, sock["wmem_alloc"] - ts)
                
                if sock["tsq_throttled"] and sock["wmem_alloc"] < tsq_limit_bytes:
                    sock["tsq_throttled"] = False
                    dur = item["complete_ns"] - sock["throttle_start_ns"]
                    sock["total_throttle_duration_ns"] += dur
                    sock["throttle_start_ns"] = None
                    log_events.append({
                        "time_ns": item["complete_ns"],
                        "type": "TSQ_UNTHROTTLED",
                        "socket": sid,
                        "wmem_alloc": sock["wmem_alloc"],
                        "throttle_duration_ns": dur
                    })

    def try_transmit(now_ns):
        nonlocal nic_busy_until_ns, nic_in_flight_bytes
        progress = True
        while progress:
            progress = False
            for sid, sock in sockets.items():
                if sock["send_buffer"] <= 0:
                    continue
                if sock["tsq_throttled"]:
                    continue
                if nic_in_flight_bytes >= bql_limit_bytes:
                    continue
                if now_ns < sock["pacing_next_ns"]:
                    continue
                    
                pkt_bytes = min(mss, sock["send_buffer"])
                
                if sock["wmem_alloc"] + skb_truesize > tsq_limit_bytes:
                    sock["tsq_throttled"] = True
                    sock["throttle_start_ns"] = now_ns
                    sock["throttle_count"] += 1
                    log_events.append({
                        "time_ns": now_ns,
                        "type": "TSQ_THROTTLED",
                        "socket": sid,
                        "wmem_alloc": sock["wmem_alloc"],
                        "limit": tsq_limit_bytes
                    })
                    continue
                    
                sock["send_buffer"] -= pkt_bytes
                sock["wmem_alloc"] += skb_truesize
                sock["packets_sent"] += 1
                sock["bytes_sent"] += pkt_bytes
                
                pacing_interval_ns = int((pkt_bytes * 1_000_000_000) / sock["pacing_rate_bps"])
                sock["pacing_next_ns"] = now_ns + pacing_interval_ns
                
                wire_tx_ns = int((pkt_bytes * 1_000_000_000) / nic_rate_bps)
                start_tx_ns = max(now_ns, nic_busy_until_ns)
                comp_ns = start_tx_ns + wire_tx_ns
                nic_busy_until_ns = comp_ns
                nic_in_flight_bytes += pkt_bytes
                
                nic_queue.append({
                    "sock_id": sid,
                    "bytes": pkt_bytes,
                    "truesize": skb_truesize,
                    "complete_ns": comp_ns
                })
                nic_queue.sort(key=lambda x: x["complete_ns"])
                progress = True

    def advance_simulation_to(target_time_ns):
        nonlocal current_time_ns
        while current_time_ns < target_time_ns:
            process_nic_completions(current_time_ns)
            try_transmit(current_time_ns)
            
            next_t = target_time_ns
            if nic_queue and nic_queue[0]["complete_ns"] < next_t:
                next_t = nic_queue[0]["complete_ns"]
            for s in sockets.values():
                if s["send_buffer"] > 0 and not s["tsq_throttled"] and s["pacing_next_ns"] > current_time_ns:
                    if s["pacing_next_ns"] < next_t:
                        next_t = s["pacing_next_ns"]
                        
            if next_t == current_time_ns:
                current_time_ns = target_time_ns
                process_nic_completions(current_time_ns)
                try_transmit(current_time_ns)
                break
                
            current_time_ns = next_t
            process_nic_completions(current_time_ns)
            try_transmit(current_time_ns)

    for op in operations:
        op_type = op["type"]
        if op_type == "APP_WRITE":
            sid = op["socket"]
            bytes_added = int(op["bytes"])
            target_time_ns = int(op.get("time_ns", current_time_ns))
            advance_simulation_to(target_time_ns)
            if sid in sockets:
                sockets[sid]["send_buffer"] += bytes_added
            try_transmit(current_time_ns)
            
        elif op_type == "SET_PACING_RATE":
            sid = op["socket"]
            new_rate = int(op["pacing_rate_bps"])
            target_time_ns = int(op.get("time_ns", current_time_ns))
            advance_simulation_to(target_time_ns)
            if sid in sockets:
                sockets[sid]["pacing_rate_bps"] = new_rate
            try_transmit(current_time_ns)
            
        elif op_type == "ADVANCE_TIME":
            target_time_ns = int(op["to_time_ns"])
            advance_simulation_to(target_time_ns)
            
    # Finalize any ongoing throttle duration
    for s in sockets.values():
        if s["tsq_throttled"] and s["throttle_start_ns"] is not None:
            s["total_throttle_duration_ns"] += (current_time_ns - s["throttle_start_ns"])
            
    summary_sockets = {}
    for sid, s in sockets.items():
        summary_sockets[sid] = {
            "packets_sent": s["packets_sent"],
            "bytes_sent": s["bytes_sent"],
            "remaining_buffer": s["send_buffer"],
            "wmem_alloc": s["wmem_alloc"],
            "tsq_throttled": s["tsq_throttled"],
            "throttle_count": s["throttle_count"],
            "total_throttle_duration_ns": s["total_throttle_duration_ns"]
        }
        
    result = {
        "final_time_ns": current_time_ns,
        "nic_in_flight_bytes": nic_in_flight_bytes,
        "nic_queued_packets": len(nic_queue),
        "sockets": summary_sockets,
        "events_count": len(log_events)
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
