import sys
import json
import ipaddress

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def ip_in_cidrs(ip_str, cidrs):
    try:
        ip = ipaddress.ip_address(ip_str)
        for c in cidrs:
            if "/" in c:
                net = ipaddress.ip_network(c, strict=False)
            else:
                net = ipaddress.ip_network(f"{c}/32", strict=False)
            if ip in net:
                return True
    except ValueError:
        return False
    return False

def simulate_xdp_engine(input_data):
    umem_config = input_data.get("umem_config", {})
    frame_size = umem_config.get("frame_size", 2048)
    total_frames = umem_config.get("total_frames", 64)
    
    # Fill Ring
    fill_ring = list(input_data.get("rings_initial", {}).get("fill_ring", []))
    
    # BPF Rules & Maps
    bpf_rules = input_data.get("bpf_rules", {})
    blacklist_cidrs = bpf_rules.get("blacklist_cidrs", [])
    redirect_map = bpf_rules.get("redirect_map", {})
    reflect_ports = set(bpf_rules.get("reflect_ports", []))
    
    # Token Bucket Rate Limiting per IP
    rate_limit_config = bpf_rules.get("rate_limiting", {})
    rl_enabled = rate_limit_config.get("enabled", False)
    rl_capacity = rate_limit_config.get("capacity", 10)
    rl_refill_rate = rate_limit_config.get("refill_rate", 5)
    rl_exempt = set(rate_limit_config.get("exempt_ips", []))
    
    ip_buckets = {}
    
    # Sockets
    sockets = {}
    for s_id in input_data.get("sockets", ["xsk0"]):
        sockets[s_id] = {
            "rx_ring": [],
            "completion_ring": [],
            "packets_received": 0,
            "packets_transmitted": 0
        }
        
    tx_ring = []
    
    stats = {
        "xdp_drop_blacklist": 0,
        "xdp_drop_ratelimit": 0,
        "xdp_pass": 0,
        "xdp_tx": 0,
        "xdp_redirect": 0,
        "rx_starvation_drop": 0,
        "skb_allocations": 0,
        "tx_completed": 0
    }
    
    packet_logs = []
    
    for event in input_data.get("events", []):
        etype = event.get("type")
        
        if etype == "RX_PACKET":
            pkt_id = event["pkt_id"]
            timestamp_ms = event.get("timestamp_ms", 0)
            src_ip = event.get("src_ip", "")
            dst_ip = event.get("dst_ip", "")
            proto = event.get("proto", "TCP").upper()
            src_port = event.get("src_port", 0)
            dst_port = event.get("dst_port", 0)
            pkt_len = event.get("len", 64)
            src_mac = event.get("src_mac", "00:00:00:00:00:01")
            dst_mac = event.get("dst_mac", "00:00:00:00:00:02")
            
            # 1. Blacklist Check
            if ip_in_cidrs(src_ip, blacklist_cidrs) or ip_in_cidrs(dst_ip, blacklist_cidrs):
                stats["xdp_drop_blacklist"] += 1
                packet_logs.append({
                    "pkt_id": pkt_id,
                    "action": "XDP_DROP",
                    "reason": "BLACKLIST_MATCH",
                    "frame_id": None
                })
                continue
                
            # 2. Token Bucket Rate Limiting per IP
            if rl_enabled and src_ip not in rl_exempt:
                if src_ip not in ip_buckets:
                    ip_buckets[src_ip] = {"tokens": float(rl_capacity), "last_ms": timestamp_ms}
                else:
                    b = ip_buckets[src_ip]
                    elapsed_sec = max(0.0, (timestamp_ms - b["last_ms"]) / 1000.0)
                    b["tokens"] = min(float(rl_capacity), b["tokens"] + elapsed_sec * rl_refill_rate)
                    b["last_ms"] = timestamp_ms
                
                if ip_buckets[src_ip]["tokens"] < 1.0:
                    stats["xdp_drop_ratelimit"] += 1
                    packet_logs.append({
                        "pkt_id": pkt_id,
                        "action": "XDP_DROP",
                        "reason": "RATE_LIMITED",
                        "frame_id": None
                    })
                    continue
                else:
                    ip_buckets[src_ip]["tokens"] -= 1.0
                    
            # 3. Reflect Port (XDP_TX)
            if dst_port in reflect_ports:
                stats["xdp_tx"] += 1
                packet_logs.append({
                    "pkt_id": pkt_id,
                    "action": "XDP_TX",
                    "details": {
                        "reflected_dst_mac": src_mac,
                        "reflected_src_mac": dst_mac,
                        "len": pkt_len
                    },
                    "frame_id": None
                })
                continue
                
            # 4. Redirect Map (AF_XDP Zero-Copy)
            lookup_key = f"{proto}:{dst_port}"
            target_socket = redirect_map.get(lookup_key)
            if not target_socket:
                lookup_key_ip = f"{src_ip}:{dst_port}"
                target_socket = redirect_map.get(lookup_key_ip)
                
            if target_socket and target_socket in sockets:
                if not fill_ring:
                    stats["rx_starvation_drop"] += 1
                    packet_logs.append({
                        "pkt_id": pkt_id,
                        "action": "DROP_STARVATION",
                        "reason": "FILL_RING_EMPTY",
                        "frame_id": None
                    })
                else:
                    frame_id = fill_ring.pop(0)
                    sockets[target_socket]["rx_ring"].append({
                        "pkt_id": pkt_id,
                        "frame_id": frame_id,
                        "len": pkt_len
                    })
                    sockets[target_socket]["packets_received"] += 1
                    stats["xdp_redirect"] += 1
                    packet_logs.append({
                        "pkt_id": pkt_id,
                        "action": "XDP_REDIRECT",
                        "target_socket": target_socket,
                        "frame_id": frame_id
                    })
            else:
                stats["xdp_pass"] += 1
                stats["skb_allocations"] += 1
                packet_logs.append({
                    "pkt_id": pkt_id,
                    "action": "XDP_PASS",
                    "stack_path": "KERNEL_SKB_STACK",
                    "frame_id": None
                })
                
        elif etype == "USER_CONSUME_RX":
            s_id = event["socket_id"]
            count = event.get("count", 1)
            recycled = []
            if s_id in sockets:
                to_consume = min(count, len(sockets[s_id]["rx_ring"]))
                for _ in range(to_consume):
                    item = sockets[s_id]["rx_ring"].pop(0)
                    recycled.append(item["frame_id"])
                if event.get("replenish_fill", True):
                    fill_ring.extend(recycled)
            packet_logs.append({
                "event": "USER_CONSUME_RX",
                "socket_id": s_id,
                "consumed_count": len(recycled),
                "recycled_frames": recycled
            })
            
        elif etype == "USER_ENQUEUE_TX":
            s_id = event["socket_id"]
            frame_id = event["frame_id"]
            pkt_id = event["pkt_id"]
            pkt_len = event.get("len", 64)
            tx_ring.append({
                "socket_id": s_id,
                "frame_id": frame_id,
                "pkt_id": pkt_id,
                "len": pkt_len
            })
            packet_logs.append({
                "event": "USER_ENQUEUE_TX",
                "socket_id": s_id,
                "frame_id": frame_id,
                "pkt_id": pkt_id
            })
            
        elif etype == "TX_POLL":
            flushed = len(tx_ring)
            for item in tx_ring:
                s_id = item["socket_id"]
                if s_id in sockets:
                    sockets[s_id]["completion_ring"].append(item["frame_id"])
                    sockets[s_id]["packets_transmitted"] += 1
                stats["tx_completed"] += 1
            tx_ring.clear()
            packet_logs.append({
                "event": "TX_POLL",
                "flushed_packets": flushed
            })
            
        elif etype == "USER_CONSUME_COMPLETION":
            s_id = event["socket_id"]
            count = event.get("count", 1)
            reclaimed = []
            if s_id in sockets:
                to_reclaim = min(count, len(sockets[s_id]["completion_ring"]))
                for _ in range(to_reclaim):
                    f_id = sockets[s_id]["completion_ring"].pop(0)
                    reclaimed.append(f_id)
                if event.get("return_to_fill", False):
                    fill_ring.extend(reclaimed)
            packet_logs.append({
                "event": "USER_CONSUME_COMPLETION",
                "socket_id": s_id,
                "reclaimed_count": len(reclaimed),
                "reclaimed_frames": reclaimed
            })

    socket_reports = {}
    for s_id, s_data in sockets.items():
        socket_reports[s_id] = {
            "rx_ring_remaining": len(s_data["rx_ring"]),
            "completion_ring_remaining": len(s_data["completion_ring"]),
            "packets_received": s_data["packets_received"],
            "packets_transmitted": s_data["packets_transmitted"]
        }
        
    total_rx_valid = (
        stats["xdp_drop_blacklist"] +
        stats["xdp_drop_ratelimit"] +
        stats["xdp_pass"] +
        stats["xdp_tx"] +
        stats["xdp_redirect"] +
        stats["rx_starvation_drop"]
    )
    total_drops = stats["xdp_drop_blacklist"] + stats["xdp_drop_ratelimit"] + stats["rx_starvation_drop"]
    surviving_packets = total_rx_valid - total_drops
    zero_copy_ratio = round((stats["xdp_redirect"] / max(1, surviving_packets)) * 100, 2)
    
    return {
        "stats": stats,
        "zero_copy_ratio_pct": zero_copy_ratio,
        "fill_ring_remaining": len(fill_ring),
        "tx_ring_remaining": len(tx_ring),
        "socket_reports": socket_reports,
        "packet_logs": packet_logs
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_xdp_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
