import json
import math
import sys

def solve(input_data):
    protocol = input_data.get("protocol", "HTTP/2")
    streams = input_data.get("streams", [])
    network = input_data.get("network", {})
    config = input_data.get("config", {})

    rtt_ms = float(network.get("rtt_ms", 50.0))
    one_way_latency = rtt_ms / 2.0
    packet_size = int(network.get("packet_size", 1000))
    packet_interval_ms = float(network.get("packet_interval_ms", 10.0))
    
    tcp_handshake_ms = float(config.get("tcp_handshake_ms", rtt_ms))
    quic_handshake_ms = float(config.get("quic_handshake_ms", rtt_ms))
    handover_events = network.get("handover_events", [])
    dropped_spec = network.get("dropped_packets", [])

    dropped_set = set()
    for d in dropped_spec:
        dropped_set.add((d["stream_id"], d["chunk_idx"]))

    stream_chunks = {}
    for s in streams:
        sid = s["stream_id"]
        size = s["size_bytes"]
        num_chunks = max(1, math.ceil(size / packet_size))
        stream_chunks[sid] = num_chunks

    total_hol_blocking_delay_ms = 0.0
    handover_reconnect_overhead_ms = 0.0
    reconnected_count = 0
    total_retransmissions = len(dropped_set)

    stream_completion_times = {}
    stream_hol_delays = {s["stream_id"]: 0.0 for s in streams}

    if protocol == "HTTP/1.1":
        max_conns = int(config.get("http1_max_connections", 6))
        conn_available_time = [tcp_handshake_ms] * max_conns
        
        for s in streams:
            sid = s["stream_id"]
            num_chunks = stream_chunks[sid]
            conn_idx = min(range(max_conns), key=lambda i: conn_available_time[i])
            current_t = conn_available_time[conn_idx]
            
            for c_idx in range(num_chunks):
                send_t = current_t
                arrive_t = send_t + one_way_latency
                
                for h in handover_events:
                    ht = float(h["trigger_time_ms"])
                    if send_t <= ht < arrive_t:
                        reconnected_count += 1
                        handover_reconnect_overhead_ms += tcp_handshake_ms
                        current_t = ht + tcp_handshake_ms
                        send_t = current_t
                        arrive_t = send_t + one_way_latency

                if (sid, c_idx) in dropped_set:
                    retransmit_arrive_t = send_t + rtt_ms + one_way_latency
                    current_t = max(current_t + packet_interval_ms, retransmit_arrive_t)
                else:
                    current_t = max(current_t + packet_interval_ms, arrive_t)

            stream_completion_times[sid] = round(current_t, 2)
            conn_available_time[conn_idx] = current_t

    elif protocol == "HTTP/2":
        conn_start = tcp_handshake_ms
        all_chunks = []
        max_chunks = max(stream_chunks.values()) if stream_chunks else 0
        for c in range(max_chunks):
            for s in streams:
                sid = s["stream_id"]
                if c < stream_chunks[sid]:
                    all_chunks.append((sid, c))
        
        current_send_t = conn_start
        l4_arrivals = []
        
        for sid, c_idx in all_chunks:
            for h in handover_events:
                ht = float(h["trigger_time_ms"])
                if current_send_t <= ht < current_send_t + one_way_latency:
                    reconnected_count += 1
                    handover_reconnect_overhead_ms += tcp_handshake_ms
                    current_send_t = ht + tcp_handshake_ms

            send_t = current_send_t
            if (sid, c_idx) in dropped_set:
                l4_arrive_t = send_t + rtt_ms + one_way_latency
            else:
                l4_arrive_t = send_t + one_way_latency
            
            l4_arrivals.append((sid, c_idx, send_t, l4_arrive_t))
            current_send_t += packet_interval_ms

        l7_delivery_t = []
        for i, (sid, c_idx, send_t, l4_arr) in enumerate(l4_arrivals):
            if i == 0:
                deliv_t = l4_arr
            else:
                prev_deliv = l7_delivery_t[i-1]
                deliv_t = max(l4_arr, prev_deliv)
            
            hol_delay = max(0.0, deliv_t - l4_arr)
            if hol_delay > 0:
                stream_hol_delays[sid] += hol_delay
                total_hol_blocking_delay_ms += hol_delay
            
            l7_delivery_t.append(deliv_t)
            stream_completion_times[sid] = round(deliv_t, 2)

    elif protocol == "HTTP/3":
        conn_start = quic_handshake_ms
        all_chunks = []
        max_chunks = max(stream_chunks.values()) if stream_chunks else 0
        for c in range(max_chunks):
            for s in streams:
                sid = s["stream_id"]
                if c < stream_chunks[sid]:
                    all_chunks.append((sid, c))
        
        current_send_t = conn_start
        l4_arrivals = []
        
        for sid, c_idx in all_chunks:
            send_t = current_send_t
            if (sid, c_idx) in dropped_set:
                l4_arrive_t = send_t + rtt_ms + one_way_latency
            else:
                l4_arrive_t = send_t + one_way_latency
            
            l4_arrivals.append((sid, c_idx, send_t, l4_arrive_t))
            current_send_t += packet_interval_ms

        stream_last_deliv = {s["stream_id"]: 0.0 for s in streams}
        
        for sid, c_idx, send_t, l4_arr in l4_arrivals:
            prev_stream_deliv = stream_last_deliv[sid]
            deliv_t = max(l4_arr, prev_stream_deliv)
            stream_last_deliv[sid] = deliv_t
            stream_completion_times[sid] = round(deliv_t, 2)

    total_elapsed = max(stream_completion_times.values()) if stream_completion_times else 0.0

    stream_results = []
    for s in streams:
        sid = s["stream_id"]
        stream_results.append({
            "stream_id": sid,
            "size_bytes": s["size_bytes"],
            "completed_at_ms": stream_completion_times[sid],
            "hol_blocked_ms": round(stream_hol_delays[sid], 2)
        })

    if protocol == "HTTP/1.1":
        diag = "HTTP/1.1 opened multiple TCP connections. Per-connection packet drops did not block other connections, but multiple handshakes and head-of-line blocking per connection remain."
    elif protocol == "HTTP/2":
        if total_hol_blocking_delay_ms > 0:
            diag = f"CRITICAL: TCP-level Head-of-Line blocking occurred! Single TCP connection stalled all streams for {total_hol_blocking_delay_ms:.1f}ms due to packet drops."
        elif reconnected_count > 0:
            diag = f"WARNING: Handover caused TCP connection reset. Reconnection penalty added {handover_reconnect_overhead_ms:.1f}ms."
        else:
            diag = "HTTP/2 optimal multiplexing on lossless network."
    else: # HTTP/3
        diag = "HTTP/3 (QUIC) achieved zero inter-stream Head-of-Line blocking and seamless Connection Migration (0-RTT handover)."

    return {
        "protocol": protocol,
        "total_elapsed_time_ms": round(total_elapsed, 2),
        "streams": stream_results,
        "metrics": {
            "total_hol_blocking_delay_ms": round(total_hol_blocking_delay_ms, 2),
            "handover_reconnect_overhead_ms": round(handover_reconnect_overhead_ms, 2),
            "reconnected_count": reconnected_count,
            "total_retransmissions": total_retransmissions
        },
        "diagnosis": diag
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
