import json
import heapq
import sys

def solve(data):
    producer_config = data.get("producer_config", {})
    enable_idempotence = producer_config.get("enable_idempotence", False)
    max_in_flight = producer_config.get("max_in_flight_requests_per_connection", 5)
    retries = producer_config.get("retries", 3)
    retry_backoff_ms = producer_config.get("retry_backoff_ms", 100)
    request_timeout_ms = producer_config.get("request_timeout_ms", 150)
    
    network_profile = data.get("network_profile", {})
    base_rtt_ms = network_profile.get("base_rtt_ms", 20)
    one_way_delay = base_rtt_ms // 2
    
    raw_messages = data.get("messages", [])
    
    # Event simulation
    # Events:
    # 1. ("SEND_REQUEST", time, msg_idx, attempt)
    # 2. ("RECEIVE_AT_BROKER", time, msg_idx, attempt)
    # 3. ("TIMEOUT", time, msg_idx, attempt)
    # 4. ("RECEIVE_ACK_AT_PRODUCER", time, msg_idx, attempt)
    
    events = []
    
    # Message metadata
    # msg_idx: {msg_id, payload, seq_num, acked, attempts}
    msgs = []
    for i, m in enumerate(raw_messages):
        msgs.append({
            "idx": i,
            "msg_id": m.get("msg_id", f"MSG_{i}"),
            "payload": m.get("payload", ""),
            "seq_num": i,
            "drop_request": m.get("network_drop_first_attempt", False),
            "drop_ack": m.get("ack_drop_first_attempt", False),
            "extra_delay_ms": m.get("extra_delay_ms", 0),
            "attempts": 0,
            "acked": False
        })
        
    in_flight_count = 0
    max_in_flight_observed = 0
    next_to_send_idx = 0
    current_time = 0
    
    partition_log = []
    expected_sequence = 0
    broker_held_queue = [] # for idempotence: holding packets arriving out-of-order
    
    out_of_order_exceptions_handled = 0
    duplicate_messages_dropped = 0
    
    # Schedule initial sends
    def try_send_next():
        nonlocal in_flight_count, next_to_send_idx, max_in_flight_observed
        while next_to_send_idx < len(msgs) and in_flight_count < max_in_flight:
            m = msgs[next_to_send_idx]
            heapq.heappush(events, (current_time, "SEND_REQUEST", m["idx"], m["attempts"]))
            in_flight_count += 1
            max_in_flight_observed = max(max_in_flight_observed, in_flight_count)
            next_to_send_idx += 1

    try_send_next()
    
    # Active timeout trackers: (msg_idx, attempt) -> valid?
    active_attempts = {}
    
    while events:
        evt = heapq.heappop(events)
        time, ev_type, m_idx, attempt = evt
        current_time = time
        m = msgs[m_idx]
        
        if ev_type == "SEND_REQUEST":
            m["attempts"] += 1
            active_attempts[(m_idx, attempt)] = True
            
            # Check if this attempt should be dropped in flight
            is_first_attempt = (attempt == 0)
            req_dropped = is_first_attempt and m["drop_request"]
            
            # Schedule timeout
            heapq.heappush(events, (current_time + request_timeout_ms, "TIMEOUT", m_idx, attempt))
            
            if not req_dropped:
                delay = one_way_delay + (m["extra_delay_ms"] if is_first_attempt else 0)
                broker_arrive_time = current_time + delay
                heapq.heappush(events, (broker_arrive_time, "RECEIVE_AT_BROKER", m_idx, attempt))
                
        elif ev_type == "TIMEOUT":
            if (m_idx, attempt) in active_attempts and active_attempts[(m_idx, attempt)] and not m["acked"]:
                # Request timed out!
                active_attempts[(m_idx, attempt)] = False
                in_flight_count -= 1
                if m["attempts"] <= retries:
                    retry_time = current_time + retry_backoff_ms
                    # Schedule retry
                    heapq.heappush(events, (retry_time, "SEND_REQUEST", m_idx, m["attempts"]))
                    in_flight_count += 1
                    max_in_flight_observed = max(max_in_flight_observed, in_flight_count)
                try_send_next()
                
        elif ev_type == "RECEIVE_AT_BROKER":
            # Packet reached broker
            seq = m["seq_num"]
            ack_dropped = (attempt == 0 and m["drop_ack"])
            
            if not enable_idempotence:
                # Non-idempotent: broker blindly commits any arriving packet!
                partition_log.append({
                    "offset": len(partition_log),
                    "msg_id": m["msg_id"],
                    "payload": m["payload"],
                    "seq_num": seq,
                    "commit_time_ms": current_time
                })
                # Send ACK back if not dropped
                if not ack_dropped:
                    heapq.heappush(events, (current_time + one_way_delay, "RECEIVE_ACK_AT_PRODUCER", m_idx, attempt))
            else:
                # Idempotent producer logic
                if seq == expected_sequence:
                    # Exactly what broker expects
                    partition_log.append({
                        "offset": len(partition_log),
                        "msg_id": m["msg_id"],
                        "payload": m["payload"],
                        "seq_num": seq,
                        "commit_time_ms": current_time
                    })
                    expected_sequence += 1
                    
                    # Check held queue for consecutive messages
                    broker_held_queue.sort(key=lambda x: x[0])
                    while broker_held_queue and broker_held_queue[0][0] == expected_sequence:
                        h_seq, h_m_idx, h_att, h_ack_drop = broker_held_queue.pop(0)
                        hm = msgs[h_m_idx]
                        partition_log.append({
                            "offset": len(partition_log),
                            "msg_id": hm["msg_id"],
                            "payload": hm["payload"],
                            "seq_num": h_seq,
                            "commit_time_ms": current_time
                        })
                        expected_sequence += 1
                        if not h_ack_drop:
                            heapq.heappush(events, (current_time + one_way_delay, "RECEIVE_ACK_AT_PRODUCER", h_m_idx, h_att))
                            
                    if not ack_dropped:
                        heapq.heappush(events, (current_time + one_way_delay, "RECEIVE_ACK_AT_PRODUCER", m_idx, attempt))
                        
                elif seq < expected_sequence:
                    # Duplicate message!
                    duplicate_messages_dropped += 1
                    # Do not append to log, but return ACK so producer knows it's committed!
                    if not ack_dropped:
                        heapq.heappush(events, (current_time + one_way_delay, "RECEIVE_ACK_AT_PRODUCER", m_idx, attempt))
                        
                else: # seq > expected_sequence
                    # Out-of-order arrival!
                    out_of_order_exceptions_handled += 1
                    # In Kafka broker with in-flight <= 5, broker holds the out-of-order batch
                    # until the missing sequence arrives, or rejects with OutOfOrderSequenceException
                    # Here we hold it in the broker buffer if in-flight <= 5
                    if max_in_flight <= 5:
                        broker_held_queue.append((seq, m_idx, attempt, ack_dropped))
                    else:
                        # Rejection! Producer must handle
                        pass

        elif ev_type == "RECEIVE_ACK_AT_PRODUCER":
            if (m_idx, attempt) in active_attempts and active_attempts[(m_idx, attempt)]:
                active_attempts[(m_idx, attempt)] = False
                if not m["acked"]:
                    m["acked"] = True
                    in_flight_count -= 1
                    try_send_next()

    # Post-analysis
    committed_msg_ids = [p["msg_id"] for p in partition_log]
    expected_msg_ids = [m["msg_id"] for m in raw_messages]
    
    # Reordering check:
    # Filter distinct msg_ids in order of appearance
    distinct_order = []
    seen = set()
    for mid in committed_msg_ids:
        if mid not in seen:
            distinct_order.append(mid)
            seen.add(mid)
            
    is_reordered = (distinct_order != expected_msg_ids[:len(distinct_order)])
    is_duplicated = (len(committed_msg_ids) != len(set(committed_msg_ids)))
    
    # Verdict determination
    if not enable_idempotence and is_reordered:
        verdict = "NON_IDEMPOTENT_REORDERING_DISASTER"
    elif not enable_idempotence and is_duplicated:
        verdict = "NON_IDEMPOTENT_DUPLICATION_DISASTER"
    elif not enable_idempotence and max_in_flight == 1:
        verdict = "IN_FLIGHT_1_RTT_BOTTLENECK"
    elif enable_idempotence and not is_reordered and not is_duplicated:
        verdict = "IDEMPOTENT_PRODUCER_EXACTLY_ONCE_IN_ORDER"
    else:
        verdict = "BALANCED_EXECUTION"
        
    summary = {
        "enable_idempotence": enable_idempotence,
        "max_in_flight_requests_per_connection": max_in_flight,
        "total_messages_submitted": len(raw_messages),
        "total_messages_committed": len(partition_log),
        "distinct_messages_committed": len(set(committed_msg_ids)),
        "is_reordered": is_reordered,
        "is_duplicated": is_duplicated,
        "max_in_flight_observed": max_in_flight_observed,
        "out_of_order_exceptions_handled": out_of_order_exceptions_handled,
        "duplicate_messages_dropped": duplicate_messages_dropped,
        "total_elapsed_ms": current_time,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "partition_log": partition_log
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
