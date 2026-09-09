import json
import sys

def simulate_port_exhaustion(data):
    cfg = data["network_config"]
    tw_reuse = cfg.get("tcp_tw_reuse", 0)
    timestamps = cfg.get("tcp_timestamps", 1)
    max_tw_buckets = cfg.get("tcp_max_tw_buckets", 10000)
    port_start = cfg.get("port_range_start", 32768)
    port_end = cfg.get("port_range_end", 60999)
    egress_ips = cfg.get("egress_ips", ["192.168.1.10"])
    keepalive_enabled = cfg.get("http_keepalive_enabled", False)
    pool_size = cfg.get("connection_pool_size", 0)

    total_ports_per_ip = max(1, port_end - port_start + 1)
    num_egress_ips = len(egress_ips)
    total_ephemeral_tuples = total_ports_per_ip * num_egress_ips

    tw_sockets = {}
    active_pool_conns = 0

    successful_requests = 0
    eaddrnotavail_errors = 0
    tw_bucket_overflow_resets = 0
    tw_reused_count = 0
    pool_hits = 0
    current_sec = 0

    port_ptrs = {ip: port_start for ip in egress_ips}
    ip_index = 0

    def cleanup_expired(now_sec):
        expired = [k for k, exp in tw_sockets.items() if exp <= now_sec]
        for k in expired:
            del tw_sockets[k]

    def try_allocate_port(now_sec):
        nonlocal ip_index, tw_reused_count, eaddrnotavail_errors

        for _ in range(num_egress_ips):
            src_ip = egress_ips[ip_index]
            ip_index = (ip_index + 1) % num_egress_ips

            start_p = port_ptrs[src_ip]
            for offset in range(total_ports_per_ip):
                p = port_start + ((start_p - port_start + offset) % total_ports_per_ip)
                key = (src_ip, p)
                if key not in tw_sockets:
                    port_ptrs[src_ip] = p + 1
                    return (src_ip, p, False)
                else:
                    if tw_reuse >= 1 and timestamps == 1:
                        port_ptrs[src_ip] = p + 1
                        tw_reused_count += 1
                        return (src_ip, p, True)

        eaddrnotavail_errors += 1
        return None

    def process_request(now_sec):
        nonlocal successful_requests, active_pool_conns, pool_hits, tw_bucket_overflow_resets

        cleanup_expired(now_sec)

        if keepalive_enabled and pool_size > 0:
            if active_pool_conns < pool_size:
                active_pool_conns += 1
            pool_hits += 1
            successful_requests += 1
            return True

        alloc = try_allocate_port(now_sec)
        if not alloc:
            return False

        src_ip, port, was_reused = alloc
        successful_requests += 1

        expire_sec = now_sec + 60
        if len(tw_sockets) >= max_tw_buckets:
            tw_bucket_overflow_resets += 1
            oldest_k = min(tw_sockets, key=tw_sockets.get)
            del tw_sockets[oldest_k]

        tw_sockets[(src_ip, port)] = expire_sec
        return True

    events = sorted(data.get("events", []), key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]
        current_sec = ev.get("time_sec", current_sec)

        if ev_type == "OUTBOUND_REQUEST_BATCH":
            count = ev.get("count", 1)
            for _ in range(count):
                process_request(current_sec)

        elif ev_type == "DRAIN_TIME_WAIT":
            cleanup_expired(current_sec)

    cleanup_expired(current_sec)

    # Diagnosis Hierarchy
    if eaddrnotavail_errors > 0:
        if tw_reuse >= 1 and timestamps == 0:
            root_cause = "TCP_TIMESTAMP_DISABLED_TW_REUSE_INEFFECTIVE"
        else:
            root_cause = "TCP_EPHEMERAL_PORT_EXHAUSTION_EADDRNOTAVAIL"
    elif tw_bucket_overflow_resets > 0:
        root_cause = "TCP_TW_BUCKET_OVERFLOW_RST_STORM"
    else:
        root_cause = "STABLE_OUTBOUND_NETWORK_THROUGHPUT"

    recommendations = []
    if eaddrnotavail_errors > 0 or tw_reuse == 0:
        if timestamps == 0:
            recommendations.append("ENABLE_TCP_TIMESTAMPS_FOR_PAWS")
        if tw_reuse == 0:
            recommendations.append("ENABLE_TCP_TW_REUSE_SYSCTL")
    if not keepalive_enabled or pool_size == 0:
        recommendations.append("ENABLE_HTTP_KEEPALIVE_CONNECTION_POOLING")
    if num_egress_ips == 1 and total_ephemeral_tuples <= 30000:
        recommendations.append("SCALE_EGRESS_SOURCE_IPS_AND_EXPAND_PORT_RANGE")
    if tw_bucket_overflow_resets > 0 or max_tw_buckets <= 10000:
        recommendations.append("INCREASE_TCP_MAX_TW_BUCKETS")

    if not recommendations:
        recommendations.append("MONITOR_ESTABLISHED_AND_TIME_WAIT_SOCKETS")

    return {
        "final_state": {
            "current_sec": current_sec,
            "active_time_wait_sockets": len(tw_sockets),
            "total_ephemeral_tuples": total_ephemeral_tuples,
            "active_pool_connections": active_pool_conns
        },
        "metrics": {
            "successful_requests": successful_requests,
            "eaddrnotavail_errors": eaddrnotavail_errors,
            "tw_bucket_overflow_resets": tw_bucket_overflow_resets,
            "tw_reused_count": tw_reused_count,
            "pool_hits": pool_hits
        },
        "root_cause": root_cause,
        "recommendations": recommendations
    }

def main():
    try:
        input_data = sys.stdin.read().strip()
        if not input_data:
            return
        data = json.loads(input_data)
        result = simulate_port_exhaustion(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
