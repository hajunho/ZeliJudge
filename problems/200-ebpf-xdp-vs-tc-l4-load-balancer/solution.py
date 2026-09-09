import sys
import json
import hashlib

def maglev_permutation(backend_id, table_size):
    h1 = int(hashlib.md5((backend_id + "_1").encode()).hexdigest(), 16) % table_size
    h2 = int(hashlib.md5((backend_id + "_2").encode()).hexdigest(), 16) % (table_size - 1) + 1
    return h1, h2

def build_maglev_table(healthy_backends, table_size=1021):
    if not healthy_backends:
        return []
    
    perms = {}
    for b in healthy_backends:
        perms[b["id"]] = maglev_permutation(b["id"], table_size)
        
    next_idx = {b["id"]: 0 for b in healthy_backends}
    entry = [-1] * table_size
    filled = 0
    
    weighted_b_ids = []
    for b in healthy_backends:
        w = max(1, b.get("weight", 1))
        weighted_b_ids.extend([b["id"]] * w)
        
    w_len = len(weighted_b_ids)
    turn = 0
    while filled < table_size:
        cur_b = weighted_b_ids[turn % w_len]
        offset, skip = perms[cur_b]
        c = next_idx[cur_b]
        
        loc = (offset + c * skip) % table_size
        while entry[loc] != -1:
            c += 1
            loc = (offset + c * skip) % table_size
        entry[loc] = cur_b
        next_idx[cur_b] = c + 1
        filled += 1
        turn += 1
        
    return entry

def simulate_l4_lb(input_data):
    vip = input_data.get("vip", "198.51.100.1:443")
    mode = input_data.get("mode", "XDP_KATRAN_OPTIMAL")
    config = input_data.get("config", {})
    conntrack_capacity = config.get("conntrack_capacity", 1000)
    maglev_table_size = config.get("maglev_table_size", 1021)
    lru_connection_limit = config.get("lru_connection_limit", 50000)
    
    initial_backends = input_data.get("backends", [])
    traffic_events = input_data.get("traffic_events", [])
    backend_updates = input_data.get("backend_updates", [])
    
    backends = {b["id"]: dict(b) for b in initial_backends}
    
    all_events = []
    for ev in traffic_events:
        all_events.append((ev["timestamp_ms"], "PACKET", ev))
    for bu in backend_updates:
        all_events.append((bu["timestamp_ms"], "BACKEND_UPDATE", bu))
    all_events.sort(key=lambda x: (x[0], 0 if x[1] == "BACKEND_UPDATE" else 1))
    
    cached_healthy = [b for b in backends.values() if b.get("healthy", True)]
    maglev_table = build_maglev_table(cached_healthy, maglev_table_size)
    
    connection_table = {}
    
    total_ingress_packets = 0
    total_ingress_bytes = 0
    forwarded_packets = 0
    dropped_packets = 0
    drop_reasons = {}
    backend_distribution = {bid: 0 for bid in backends}
    broken_connection_resets = 0
    lb_egress_bytes = 0
    cpu_cost_units = 0.0
    conntrack_peak_usage = 0
    
    for ts, ev_type, ev_data in all_events:
        if ev_type == "BACKEND_UPDATE":
            action = ev_data["action"]
            bid = ev_data["backend_id"]
            if action == "DOWN":
                if bid in backends:
                    backends[bid]["healthy"] = False
            elif action == "UP":
                if bid in backends:
                    backends[bid]["healthy"] = True
            elif action == "WEIGHT_CHANGE":
                if bid in backends:
                    backends[bid]["weight"] = ev_data.get("weight", 1)
            elif action == "ADD":
                backends[bid] = {
                    "id": bid,
                    "ip": ev_data.get("ip", "10.0.1.99:443"),
                    "weight": ev_data.get("weight", 1),
                    "healthy": True
                }
                backend_distribution[bid] = 0
            elif action == "DRAIN":
                if bid in backends:
                    backends[bid]["draining"] = True
                    
            active_backends = [b for b in backends.values() if b.get("healthy", True) and not b.get("draining", False)]
            maglev_table = build_maglev_table(active_backends, maglev_table_size)
            continue
            
        total_ingress_packets += 1
        pkt_bytes = ev_data.get("payload_bytes", 64)
        total_ingress_bytes += pkt_bytes
        
        flow = ev_data["flow"]
        flow_key = f"{flow['src_ip']}:{flow['src_port']}->{vip}:{flow.get('proto', 'TCP')}"
        flags = ev_data.get("flags", [])
        
        if mode == "XDP_KATRAN_OPTIMAL":
            cpu_cost_units += 0.1
        elif mode == "TC_EBPF_DSR":
            cpu_cost_units += 0.5
        else:
            cpu_cost_units += 2.0
            
        existing_entry = connection_table.get(flow_key)
        assigned_backend = None
        
        if mode == "TRADITIONAL_CONNTRACK_NAT":
            if existing_entry:
                assigned_backend = existing_entry["backend"]
                existing_entry["last_seen"] = ts
            else:
                if len(connection_table) >= conntrack_capacity:
                    dropped_packets += 1
                    drop_reasons["CONNTRACK_TABLE_EXHAUSTION_DROP"] = drop_reasons.get("CONNTRACK_TABLE_EXHAUSTION_DROP", 0) + 1
                    continue
                else:
                    active = [b for b in backends.values() if b.get("healthy", True)]
                    if not active:
                        dropped_packets += 1
                        drop_reasons["NO_HEALTHY_BACKEND"] = drop_reasons.get("NO_HEALTHY_BACKEND", 0) + 1
                        continue
                    h = int(hashlib.md5(flow_key.encode()).hexdigest(), 16)
                    assigned_backend = active[h % len(active)]["id"]
                    connection_table[flow_key] = {
                        "backend": assigned_backend,
                        "last_seen": ts,
                        "created_at": ts
                    }
                    
            conntrack_peak_usage = max(conntrack_peak_usage, len(connection_table))
            lb_egress_bytes += pkt_bytes * 10
            
        else:
            if existing_entry:
                target_bid = existing_entry["backend"]
                if backends.get(target_bid, {}).get("healthy", False):
                    assigned_backend = target_bid
                    existing_entry["last_seen"] = ts
                else:
                    broken_connection_resets += 1
                    if maglev_table:
                        h = int(hashlib.md5(flow_key.encode()).hexdigest(), 16) % maglev_table_size
                        assigned_backend = maglev_table[h]
                        existing_entry["backend"] = assigned_backend
                        existing_entry["last_seen"] = ts
                    else:
                        dropped_packets += 1
                        drop_reasons["NO_HEALTHY_BACKEND"] = drop_reasons.get("NO_HEALTHY_BACKEND", 0) + 1
                        continue
            else:
                if not maglev_table:
                    dropped_packets += 1
                    drop_reasons["NO_HEALTHY_BACKEND"] = drop_reasons.get("NO_HEALTHY_BACKEND", 0) + 1
                    continue
                h = int(hashlib.md5(flow_key.encode()).hexdigest(), 16) % maglev_table_size
                assigned_backend = maglev_table[h]
                
                if len(connection_table) >= lru_connection_limit:
                    oldest_k = min(connection_table.keys(), key=lambda k: connection_table[k]["last_seen"])
                    del connection_table[oldest_k]
                    
                connection_table[flow_key] = {
                    "backend": assigned_backend,
                    "last_seen": ts,
                    "created_at": ts
                }
                
            conntrack_peak_usage = max(conntrack_peak_usage, len(connection_table))
            lb_egress_bytes += (pkt_bytes + 40)
            
        if "FIN" in flags or "RST" in flags:
            if flow_key in connection_table:
                del connection_table[flow_key]
                
        forwarded_packets += 1
        backend_distribution[assigned_backend] = backend_distribution.get(assigned_backend, 0) + 1

    if dropped_packets > 0 and "CONNTRACK_TABLE_EXHAUSTION_DROP" in drop_reasons:
        verdict = "CONNTRACK_EXHAUSTION_COLLAPSE"
    elif mode == "XDP_KATRAN_OPTIMAL":
        verdict = "OPTIMAL_XDP_DSR_LINE_RATE"
    elif mode == "TC_EBPF_DSR":
        verdict = "TC_DSR_SUBOPTIMAL"
    else:
        verdict = "TRADITIONAL_NAT_LOW_THROUGHPUT"

    return {
        "mode_used": mode,
        "metrics": {
            "total_ingress_packets": total_ingress_packets,
            "total_ingress_bytes": total_ingress_bytes,
            "forwarded_packets": forwarded_packets,
            "dropped_packets": dropped_packets,
            "drop_reasons": drop_reasons,
            "active_flows_count": len(connection_table),
            "conntrack_peak_usage": conntrack_peak_usage,
            "backend_distribution": backend_distribution,
            "broken_connection_resets": broken_connection_resets,
            "lb_egress_bytes": lb_egress_bytes,
            "cpu_processing_cost_units": round(cpu_cost_units, 2),
            "verdict": verdict
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = simulate_l4_lb(input_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
