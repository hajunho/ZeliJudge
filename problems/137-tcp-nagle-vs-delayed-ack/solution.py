import heapq
import json
import sys

def solve(data):
    mss = data.get("mss", 1460)
    rtt_ms = data.get("rtt_ms", 2)
    delayed_ack_timeout_ms = data.get("delayed_ack_timeout_ms", 40)
    tcp_nodelay = data.get("tcp_nodelay", False)
    delayed_ack_enabled = data.get("delayed_ack_enabled", True)
    
    writes = data.get("writes", [])
    writes = sorted(writes, key=lambda x: x.get("timestamp_ms", 0))
    
    one_way_delay = rtt_ms / 2.0
    
    # Priority Queue for discrete event simulation: (time, event_id, event_type, payload)
    pq = []
    event_id = 0
    
    def push_event(t, ev_type, payload):
        nonlocal event_id
        event_id += 1
        heapq.heappush(pq, (t, event_id, ev_type, payload))
        
    for w in writes:
        push_event(w.get("timestamp_ms", 0), "APP_WRITE", w.get("bytes", 0))
        
    send_buffer = 0
    in_flight_bytes = 0
    total_bytes_written = sum(w.get("bytes", 0) for w in writes)
    total_bytes_acked = 0
    
    packets_sent = 0
    total_acks_sent = 0
    nagle_stalls = 0
    delayed_ack_timeouts = 0
    quick_acks_sent = 0
    
    receiver_received_bytes = 0
    unacked_segments = 0
    delayed_ack_timer_time = None
    
    timeline = []
    final_completion_time = 0 if total_bytes_written == 0 else None
    last_event_time = 0
    
    def try_sender_transmit(current_time):
        nonlocal send_buffer, in_flight_bytes, packets_sent, nagle_stalls
        stalled_this_turn = False
        while send_buffer > 0:
            can_send = False
            if tcp_nodelay:
                can_send = True
            elif in_flight_bytes == 0:
                can_send = True
            elif send_buffer >= mss:
                can_send = True
            else:
                can_send = False
                
            if can_send:
                seg_size = min(send_buffer, mss)
                send_buffer -= seg_size
                in_flight_bytes += seg_size
                packets_sent += 1
                timeline.append({
                    "time_ms": int(current_time) if current_time == int(current_time) else round(current_time, 2),
                    "event": "PACKET_SENT",
                    "bytes": seg_size,
                    "in_flight": in_flight_bytes
                })
                push_event(current_time + one_way_delay, "PACKET_RECV", seg_size)
            else:
                if not stalled_this_turn:
                    nagle_stalls += 1
                    stalled_this_turn = True
                    timeline.append({
                        "time_ms": int(current_time) if current_time == int(current_time) else round(current_time, 2),
                        "event": "NAGLE_STALL",
                        "buffer_bytes": send_buffer,
                        "in_flight": in_flight_bytes
                    })
                break

    while pq:
        t, _, ev_type, payload = heapq.heappop(pq)
        last_event_time = t
        display_t = int(t) if t == int(t) else round(t, 2)
        
        if ev_type == "APP_WRITE":
            send_buffer += payload
            try_sender_transmit(t)
            
        elif ev_type == "PACKET_RECV":
            seg_size = payload
            receiver_received_bytes += seg_size
            timeline.append({
                "time_ms": display_t,
                "event": "PACKET_RECEIVED",
                "bytes": seg_size,
                "total_received": receiver_received_bytes
            })
            
            if not delayed_ack_enabled:
                # Immediate ACK for each packet (TCP_QUICKACK)
                total_acks_sent += 1
                push_event(t + one_way_delay, "ACK_RECV", receiver_received_bytes)
                timeline.append({
                    "time_ms": display_t,
                    "event": "ACK_SENT_IMMEDIATE",
                    "ack_bytes": receiver_received_bytes
                })
            else:
                unacked_segments += 1
                if unacked_segments >= 2:
                    # Cumulative ACK sent immediately
                    unacked_segments = 0
                    delayed_ack_timer_time = None
                    quick_acks_sent += 1
                    total_acks_sent += 1
                    push_event(t + one_way_delay, "ACK_RECV", receiver_received_bytes)
                    timeline.append({
                        "time_ms": display_t,
                        "event": "ACK_SENT_CUMULATIVE",
                        "ack_bytes": receiver_received_bytes
                    })
                else:
                    # First segment, start delayed ACK timer
                    timer_expiry = t + delayed_ack_timeout_ms
                    delayed_ack_timer_time = timer_expiry
                    push_event(timer_expiry, "DELAYED_ACK_TIMER_EXPIRE", receiver_received_bytes)
                    
        elif ev_type == "DELAYED_ACK_TIMER_EXPIRE":
            # Only fire if timer is still active and covers unacked segments
            if delayed_ack_timer_time == t and unacked_segments > 0:
                delayed_ack_timeouts += 1
                total_acks_sent += 1
                unacked_segments = 0
                delayed_ack_timer_time = None
                push_event(t + one_way_delay, "ACK_RECV", receiver_received_bytes)
                timeline.append({
                    "time_ms": display_t,
                    "event": "ACK_SENT_TIMEOUT",
                    "ack_bytes": receiver_received_bytes
                })
                
        elif ev_type == "ACK_RECV":
            ack_bytes = payload
            newly_acked = ack_bytes - total_bytes_acked
            if newly_acked > 0:
                total_bytes_acked = ack_bytes
                in_flight_bytes = max(0, in_flight_bytes - newly_acked)
                timeline.append({
                    "time_ms": display_t,
                    "event": "ACK_RECEIVED",
                    "ack_bytes": ack_bytes,
                    "in_flight": in_flight_bytes
                })
                try_sender_transmit(t)
                
                # Check if all application data is transferred and acknowledged
                if total_bytes_acked >= total_bytes_written and send_buffer == 0 and in_flight_bytes == 0 and not any(ev[2] == "APP_WRITE" for ev in pq):
                    if final_completion_time is None:
                        final_completion_time = t

    if total_bytes_written == 0:
        verdict = "NO_DATA_TRANSMITTED"
    elif nagle_stalls > 0 and delayed_ack_timeouts > 0:
        verdict = "NAGLE_DELAYED_ACK_DEADLOCK"
    elif tcp_nodelay and nagle_stalls == 0:
        verdict = "OPTIMAL_TCP_NODELAY_STREAMING"
    elif not delayed_ack_enabled:
        verdict = "QUICK_ACK_LOW_LATENCY"
    elif nagle_stalls == 0:
        verdict = "FULL_MSS_STREAMING"
    else:
        verdict = "NAGLE_STALL_NO_TIMEOUT"
        
    completion_time = final_completion_time if final_completion_time is not None else last_event_time
    
    summary = {
        "mss": mss,
        "rtt_ms": rtt_ms,
        "delayed_ack_timeout_ms": delayed_ack_timeout_ms,
        "tcp_nodelay": tcp_nodelay,
        "delayed_ack_enabled": delayed_ack_enabled,
        "total_bytes_written": total_bytes_written,
        "total_packets_sent": packets_sent,
        "total_acks_sent": total_acks_sent,
        "nagle_stalls": nagle_stalls,
        "delayed_ack_timeouts": delayed_ack_timeouts,
        "quick_acks_sent": quick_acks_sent,
        "completion_time_ms": int(completion_time) if completion_time == int(completion_time) else round(completion_time, 2),
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "sample_timeline": timeline[:10]
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
