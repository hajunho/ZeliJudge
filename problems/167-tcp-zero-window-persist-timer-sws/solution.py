import sys
import json
import heapq

def simulate_tcp_flow(config):
    mss = config.get("mss", 1000)
    rcv_buff_size = config.get("rcv_buff_size", 4000)
    rtt = config.get("rtt_ticks", 20)
    one_way_delay = rtt // 2
    initial_rto = config.get("initial_rto", 200)
    max_persist_timeout = config.get("max_persist_timeout", 1600)
    clark_enabled = config.get("clark_enabled", True)
    sender_sws_enabled = config.get("sender_sws_enabled", True)
    events_input = config.get("timeline_events", [])

    metrics = {
        "total_payload_bytes_sent": 0,
        "total_header_bytes_sent": 0,
        "total_data_packets_sent": 0,
        "zero_window_probes_sent": 0,
        "acks_sent": 0,
        "zero_window_advertised_count": 0,
        "silly_window_packets_sent": 0,
        "sws_avoidance_stalls": 0,
        "persist_timer_backoffs": 0,
        "deadlocks_prevented_by_probe": 0,
        "completion_tick": None,
        "header_overhead_ratio": 0.0,
        "verdict": ""
    }

    # Sender state (RFC 793)
    snd_una = 0
    snd_nxt = 0
    snd_wnd = rcv_buff_size
    max_advertised_wnd = rcv_buff_size
    
    app_written_total = 0
    in_persist_state = False
    current_persist_timeout = initial_rto
    persist_timer_seq = 0
    active_persist_timer_id = None
    dropped_window_update_active = False
    last_activity_tick = 0

    # Receiver state
    rcv_buff_used = 0
    rcv_nxt = 0
    receiver_last_advertised_wnd = rcv_buff_size

    event_pq = []
    event_counter = 0

    def schedule_event(tick, priority, ev_type, data):
        nonlocal event_counter
        event_counter += 1
        heapq.heappush(event_pq, (tick, priority, event_counter, ev_type, data))

    for ev in events_input:
        schedule_event(ev["tick"], 1, ev["type"], ev)

    timeline_log = []

    def get_receiver_advertised_window():
        free_space = rcv_buff_size - rcv_buff_used
        if clark_enabled:
            threshold = min(mss, rcv_buff_size // 2)
            if receiver_last_advertised_wnd == 0:
                return free_space if (free_space >= threshold or free_space == rcv_buff_size) else 0
            else:
                return free_space
        else:
            return free_space

    def try_sender_transmit(current_tick):
        nonlocal snd_nxt, snd_una, snd_wnd, in_persist_state
        nonlocal current_persist_timeout, active_persist_timer_id, persist_timer_seq

        if in_persist_state:
            return

        unsent_bytes = app_written_total - snd_nxt
        in_flight = snd_nxt - snd_una
        usable_wnd = max(0, (snd_una + snd_wnd) - snd_nxt)

        while unsent_bytes > 0 and usable_wnd > 0:
            can_send = False
            if not sender_sws_enabled:
                can_send = True
            else:
                # RFC 1122 Section 4.2.3.4:
                # 1) Full segment: min(unsent_bytes, usable_wnd) >= mss
                # 2) At least half max advertised window: min(unsent_bytes, usable_wnd) >= max_advertised_wnd // 2
                # 3) All remaining unsent data can be sent AND no in-flight unacknowledged data
                if min(unsent_bytes, usable_wnd) >= mss:
                    can_send = True
                elif min(unsent_bytes, usable_wnd) >= (max_advertised_wnd // 2):
                    can_send = True
                elif unsent_bytes <= usable_wnd and in_flight == 0:
                    can_send = True

            if not can_send:
                metrics["sws_avoidance_stalls"] += 1
                timeline_log.append({
                    "tick": current_tick,
                    "event": "SWS_AVOIDANCE_STALL",
                    "unsent_bytes": unsent_bytes,
                    "usable_wnd": usable_wnd,
                    "max_advertised_wnd": max_advertised_wnd
                })
                break

            chunk = min(unsent_bytes, usable_wnd, mss)
            if chunk == 0:
                break

            threshold_sws = min(mss, max_advertised_wnd // 2)
            if chunk < threshold_sws and not sender_sws_enabled:
                metrics["silly_window_packets_sent"] += 1

            snd_nxt += chunk
            metrics["total_payload_bytes_sent"] += chunk
            metrics["total_data_packets_sent"] += 1
            metrics["total_header_bytes_sent"] += 40

            unsent_bytes = app_written_total - snd_nxt
            in_flight = snd_nxt - snd_una
            usable_wnd = max(0, (snd_una + snd_wnd) - snd_nxt)

            timeline_log.append({
                "tick": current_tick,
                "event": "DATA_PACKET_SENT",
                "bytes": chunk,
                "in_flight": in_flight,
                "unsent": unsent_bytes
            })

            schedule_event(current_tick + one_way_delay, 2, "PACKET_ARRIVE_AT_RECEIVER", {
                "type": "DATA",
                "bytes": chunk
            })

        # If window is 0 and unsent data remains, enter persist state
        if snd_wnd == 0 and unsent_bytes > 0 and not in_persist_state:
            in_persist_state = True
            current_persist_timeout = initial_rto
            persist_timer_seq += 1
            active_persist_timer_id = persist_timer_seq
            schedule_event(current_tick + current_persist_timeout, 4, "PERSIST_TIMER_EXPIRE", {
                "timer_id": persist_timer_seq
            })
            timeline_log.append({
                "tick": current_tick,
                "event": "ENTER_PERSIST_STATE",
                "timeout": current_persist_timeout
            })

    current_tick = 0
    drop_next_window_update = False

    while event_pq:
        tick, priority, _, ev_type, data = heapq.heappop(event_pq)
        current_tick = tick
        last_activity_tick = current_tick

        if ev_type == "APP_WRITE":
            bytes_to_write = data["bytes"]
            app_written_total += bytes_to_write
            metrics["completion_tick"] = None
            timeline_log.append({
                "tick": current_tick,
                "event": "APP_WRITE",
                "bytes": bytes_to_write,
                "app_written_total": app_written_total
            })
            try_sender_transmit(current_tick)

        elif ev_type == "DROP_NEXT_WINDOW_UPDATE":
            drop_next_window_update = True
            timeline_log.append({
                "tick": current_tick,
                "event": "ARM_DROP_NEXT_WINDOW_UPDATE"
            })

        elif ev_type == "APP_READ":
            bytes_to_read = data["bytes"]
            actual_read = min(bytes_to_read, rcv_buff_used)
            rcv_buff_used -= actual_read
            timeline_log.append({
                "tick": current_tick,
                "event": "APP_READ",
                "read_bytes": actual_read,
                "rcv_buff_used": rcv_buff_used
            })
            new_wnd = get_receiver_advertised_window()
            
            # Check if window update should be sent
            should_send_update = False
            if not clark_enabled:
                if new_wnd > receiver_last_advertised_wnd:
                    should_send_update = True
            else:
                threshold = min(mss, rcv_buff_size // 2)
                if receiver_last_advertised_wnd == 0 and new_wnd >= threshold:
                    should_send_update = True
                elif new_wnd - receiver_last_advertised_wnd >= threshold or new_wnd == rcv_buff_size:
                    should_send_update = True

            if should_send_update:
                receiver_last_advertised_wnd = new_wnd
                if drop_next_window_update:
                    drop_next_window_update = False
                    dropped_window_update_active = True
                    timeline_log.append({
                        "tick": current_tick,
                        "event": "WINDOW_UPDATE_DROPPED",
                        "advertised_wnd": new_wnd
                    })
                else:
                    metrics["acks_sent"] += 1
                    metrics["total_header_bytes_sent"] += 40
                    schedule_event(current_tick + one_way_delay, 3, "ACK_ARRIVE_AT_SENDER", {
                        "ack_bytes": rcv_nxt,
                        "advertised_wnd": new_wnd,
                        "is_probe_response": False
                    })
                    timeline_log.append({
                        "tick": current_tick,
                        "event": "WINDOW_UPDATE_SENT",
                        "advertised_wnd": new_wnd
                    })

        elif ev_type == "PACKET_ARRIVE_AT_RECEIVER":
            pkt_type = data["type"]
            if pkt_type == "DATA":
                chunk = data["bytes"]
                rcv_buff_used += chunk
                rcv_nxt += chunk
                adv_wnd = get_receiver_advertised_window()
                receiver_last_advertised_wnd = adv_wnd
                if adv_wnd == 0:
                    metrics["zero_window_advertised_count"] += 1
                metrics["acks_sent"] += 1
                metrics["total_header_bytes_sent"] += 40
                schedule_event(current_tick + one_way_delay, 3, "ACK_ARRIVE_AT_SENDER", {
                    "ack_bytes": rcv_nxt,
                    "advertised_wnd": adv_wnd,
                    "is_probe_response": False
                })
                timeline_log.append({
                    "tick": current_tick,
                    "event": "DATA_ARRIVED_AT_RECEIVER",
                    "bytes": chunk,
                    "rcv_buff_used": rcv_buff_used,
                    "advertised_wnd": adv_wnd
                })

            elif pkt_type == "ZERO_WINDOW_PROBE":
                free_space = rcv_buff_size - rcv_buff_used
                probe_accepted = False
                if free_space >= 1:
                    rcv_buff_used += 1
                    rcv_nxt += 1
                    probe_accepted = True
                adv_wnd = get_receiver_advertised_window()
                receiver_last_advertised_wnd = adv_wnd
                if adv_wnd == 0:
                    metrics["zero_window_advertised_count"] += 1
                metrics["acks_sent"] += 1
                metrics["total_header_bytes_sent"] += 40
                schedule_event(current_tick + one_way_delay, 3, "ACK_ARRIVE_AT_SENDER", {
                    "ack_bytes": rcv_nxt,
                    "advertised_wnd": adv_wnd,
                    "is_probe_response": True,
                    "probe_accepted": probe_accepted
                })
                timeline_log.append({
                    "tick": current_tick,
                    "event": "PROBE_ARRIVED_AT_RECEIVER",
                    "rcv_buff_used": rcv_buff_used,
                    "probe_accepted": probe_accepted,
                    "advertised_wnd": adv_wnd
                })

        elif ev_type == "ACK_ARRIVE_AT_SENDER":
            ack_bytes = data["ack_bytes"]
            adv_wnd = data["advertised_wnd"]
            is_probe_resp = data["is_probe_response"]
            probe_accepted = data.get("probe_accepted", False)

            snd_una = ack_bytes
            snd_wnd = adv_wnd
            max_advertised_wnd = max(max_advertised_wnd, adv_wnd)

            if is_probe_resp and not probe_accepted:
                snd_nxt -= 1

            in_flight = snd_nxt - snd_una

            timeline_log.append({
                "tick": current_tick,
                "event": "ACK_ARRIVED_AT_SENDER",
                "snd_una": snd_una,
                "advertised_wnd": adv_wnd,
                "in_flight": in_flight
            })

            if adv_wnd > 0:
                if in_persist_state:
                    if dropped_window_update_active:
                        metrics["deadlocks_prevented_by_probe"] += 1
                        dropped_window_update_active = False
                    in_persist_state = False
                    active_persist_timer_id = None
                    current_persist_timeout = initial_rto
                    timeline_log.append({
                        "tick": current_tick,
                        "event": "EXIT_PERSIST_STATE",
                        "advertised_wnd": adv_wnd
                    })
                try_sender_transmit(current_tick)
            else:
                unsent = app_written_total - snd_nxt
                if is_probe_resp and in_persist_state:
                    metrics["persist_timer_backoffs"] += 1
                    current_persist_timeout = min(current_persist_timeout * 2, max_persist_timeout)
                    persist_timer_seq += 1
                    active_persist_timer_id = persist_timer_seq
                    schedule_event(current_tick + current_persist_timeout, 4, "PERSIST_TIMER_EXPIRE", {
                        "timer_id": persist_timer_seq
                    })
                    timeline_log.append({
                        "tick": current_tick,
                        "event": "PERSIST_TIMER_BACKOFF",
                        "next_timeout": current_persist_timeout
                    })
                elif not in_persist_state and unsent > 0:
                    in_persist_state = True
                    current_persist_timeout = initial_rto
                    persist_timer_seq += 1
                    active_persist_timer_id = persist_timer_seq
                    schedule_event(current_tick + current_persist_timeout, 4, "PERSIST_TIMER_EXPIRE", {
                        "timer_id": persist_timer_seq
                    })
                    timeline_log.append({
                        "tick": current_tick,
                        "event": "ENTER_PERSIST_STATE",
                        "timeout": current_persist_timeout
                    })

            # Check if all sent data is acked
            if app_written_total > 0 and snd_una >= app_written_total and (snd_nxt - snd_una) == 0:
                if metrics["completion_tick"] is None:
                    metrics["completion_tick"] = current_tick

        elif ev_type == "PERSIST_TIMER_EXPIRE":
            timer_id = data["timer_id"]
            unsent = app_written_total - snd_nxt
            if timer_id == active_persist_timer_id and in_persist_state and snd_wnd == 0 and unsent > 0:
                metrics["zero_window_probes_sent"] += 1
                metrics["total_payload_bytes_sent"] += 1
                metrics["total_header_bytes_sent"] += 40
                snd_nxt += 1
                timeline_log.append({
                    "tick": current_tick,
                    "event": "ZWP_PROBE_SENT",
                    "probe_bytes": 1,
                    "snd_nxt": snd_nxt
                })
                schedule_event(current_tick + one_way_delay, 2, "PACKET_ARRIVE_AT_RECEIVER", {
                    "type": "ZERO_WINDOW_PROBE"
                })

    if metrics["completion_tick"] is None:
        metrics["completion_tick"] = last_activity_tick

    # Overall verdict
    if metrics["silly_window_packets_sent"] > 0:
        metrics["verdict"] = "SWS_PACKET_STORM"
    elif metrics["deadlocks_prevented_by_probe"] > 0:
        metrics["verdict"] = "PERSIST_PROBE_DEADLOCK_PREVENTED"
    elif metrics["zero_window_advertised_count"] > 0:
        metrics["verdict"] = "ZERO_WINDOW_FLOW_CONTROLLED"
    else:
        metrics["verdict"] = "NORMAL_STREAMING"

    total_wire_bytes = metrics["total_payload_bytes_sent"] + metrics["total_header_bytes_sent"]
    metrics["header_overhead_ratio"] = round(metrics["total_header_bytes_sent"] / total_wire_bytes, 4) if total_wire_bytes > 0 else 0.0

    return {
        "metrics": metrics,
        "sample_timeline": timeline_log[:20]
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    config = json.loads(raw)
    result = simulate_tcp_flow(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
