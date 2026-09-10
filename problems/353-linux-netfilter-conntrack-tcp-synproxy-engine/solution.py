import sys
import json

def seq_diff(a, b):
    diff = (a - b) & 0xFFFFFFFF
    if diff >= 0x80000000:
        return diff - 0x100000000
    return diff

def seq_le(a, b):
    return seq_diff(a, b) <= 0

def seq_lt(a, b):
    return seq_diff(a, b) < 0

def seq_ge(a, b):
    return seq_diff(a, b) >= 0

def seq_gt(a, b):
    return seq_diff(a, b) > 0

TCP_CONNTRACK_NONE = "NONE"
TCP_CONNTRACK_SYN_SENT = "SYN_SENT"
TCP_CONNTRACK_SYN_RECV = "SYN_RECV"
TCP_CONNTRACK_ESTABLISHED = "ESTABLISHED"
TCP_CONNTRACK_FIN_WAIT = "FIN_WAIT"
TCP_CONNTRACK_CLOSE_WAIT = "CLOSE_WAIT"
TCP_CONNTRACK_LAST_ACK = "LAST_ACK"
TCP_CONNTRACK_TIME_WAIT = "TIME_WAIT"
TCP_CONNTRACK_CLOSE = "CLOSE"

def simulate_conntrack_tcp(input_data):
    config = input_data.get("config", {})
    synproxy_enabled = config.get("synproxy_enabled", False)
    synproxy_secret = config.get("synproxy_secret", 0x12345678)
    strict_window_tracking = config.get("strict_window_tracking", True)
    
    state = TCP_CONNTRACK_NONE
    
    dirs = {
        "ORIGINAL": {"td_end": 0, "td_maxend": 0, "td_maxwin": 1, "scale": 0},
        "REPLY": {"td_end": 0, "td_maxend": 0, "td_maxwin": 1, "scale": 0}
    }
    
    synproxy_pending_cookie = None
    synproxy_established = False
    
    packets = input_data.get("packets", [])
    packet_results = []
    
    metrics = {
        "packets_processed": 0,
        "packets_accepted": 0,
        "packets_dropped_invalid": 0,
        "synproxy_syn_cookies_generated": 0,
        "synproxy_cookies_verified": 0,
        "synproxy_spoofed_syns_dropped": 0,
        "state_transitions": 0,
        "window_probes_accepted": 0
    }
    
    for pkt in packets:
        metrics["packets_processed"] += 1
        direction = pkt.get("dir", "ORIGINAL")
        sender = dirs[direction]
        receiver = dirs["REPLY" if direction == "ORIGINAL" else "ORIGINAL"]
        
        flags = pkt.get("flags", [])
        seq = pkt.get("seq", 0) & 0xFFFFFFFF
        ack = pkt.get("ack", 0) & 0xFFFFFFFF
        length = pkt.get("len", 0)
        win = pkt.get("win", 65535) & 0xFFFF
        wscale = pkt.get("wscale", None)
        
        is_syn = "SYN" in flags
        is_ack = "ACK" in flags
        is_fin = "FIN" in flags
        is_rst = "RST" in flags
        
        action = "ACCEPT"
        reason = "NORMAL"
        new_state = state
        
        if synproxy_enabled and not synproxy_established:
            if is_syn and not is_ack and direction == "ORIGINAL":
                cookie = ((seq ^ synproxy_secret) + (win << 8) + 0xCAFE) & 0xFFFFFFFF
                synproxy_pending_cookie = cookie
                metrics["synproxy_syn_cookies_generated"] += 1
                action = "SYNPROXY_SYN_ACK_SENT"
                reason = "SYN_COOKIE_GENERATED"
                packet_results.append({
                    "pkt_id": pkt.get("id"),
                    "action": action,
                    "reason": reason,
                    "state": state,
                    "syn_cookie": cookie
                })
                continue
                
            elif is_ack and not is_syn and direction == "ORIGINAL" and synproxy_pending_cookie is not None:
                expected_ack = (synproxy_pending_cookie + 1) & 0xFFFFFFFF
                if ack == expected_ack:
                    metrics["synproxy_cookies_verified"] += 1
                    synproxy_established = True
                    state = TCP_CONNTRACK_ESTABLISHED
                    metrics["state_transitions"] += 1
                    sender["td_end"] = (seq + length) & 0xFFFFFFFF
                    sender["td_maxwin"] = max(1, win)
                    sender["td_maxend"] = (ack + max(1, win)) & 0xFFFFFFFF
                    
                    receiver["td_end"] = synproxy_pending_cookie + 1
                    receiver["td_maxwin"] = 65535
                    receiver["td_maxend"] = (seq + 65535) & 0xFFFFFFFF
                    
                    action = "SYNPROXY_HANDSHAKE_COMPLETED"
                    reason = "COOKIE_VERIFIED"
                    metrics["packets_accepted"] += 1
                    packet_results.append({
                        "pkt_id": pkt.get("id"),
                        "action": action,
                        "reason": reason,
                        "state": state
                    })
                    continue
                else:
                    metrics["synproxy_spoofed_syns_dropped"] += 1
                    metrics["packets_dropped_invalid"] += 1
                    action = "DROP"
                    reason = "INVALID_SYN_COOKIE"
                    packet_results.append({
                        "pkt_id": pkt.get("id"),
                        "action": action,
                        "reason": reason,
                        "state": state
                    })
                    continue

        if is_rst:
            if state in (TCP_CONNTRACK_ESTABLISHED, TCP_CONNTRACK_SYN_SENT, TCP_CONNTRACK_SYN_RECV, TCP_CONNTRACK_FIN_WAIT, TCP_CONNTRACK_CLOSE_WAIT):
                new_state = TCP_CONNTRACK_CLOSE
                action = "ACCEPT"
                reason = "TCP_RST"
        elif is_syn and not is_ack:
            if direction == "ORIGINAL" and state in (TCP_CONNTRACK_NONE, TCP_CONNTRACK_CLOSE, TCP_CONNTRACK_TIME_WAIT):
                new_state = TCP_CONNTRACK_SYN_SENT
                sender["td_end"] = (seq + 1) & 0xFFFFFFFF
                sender["td_maxwin"] = max(1, win)
                sender["td_maxend"] = (seq + 1 + max(1, win)) & 0xFFFFFFFF
                if wscale is not None:
                    sender["scale"] = min(14, max(0, wscale))
            else:
                action = "DROP"
                reason = "UNEXPECTED_SYN"
        elif is_syn and is_ack:
            if direction == "REPLY" and state == TCP_CONNTRACK_SYN_SENT:
                if ack == receiver["td_end"]:
                    new_state = TCP_CONNTRACK_SYN_RECV
                    sender["td_end"] = (seq + 1) & 0xFFFFFFFF
                    sender["td_maxwin"] = max(1, win)
                    sender["td_maxend"] = (ack + max(1, win)) & 0xFFFFFFFF
                    if wscale is not None:
                        sender["scale"] = min(14, max(0, wscale))
                else:
                    action = "DROP"
                    reason = "BAD_SYN_ACK"
            else:
                action = "DROP"
                reason = "UNEXPECTED_SYN_ACK"
        elif is_ack and not is_fin:
            if state == TCP_CONNTRACK_SYN_RECV and direction == "ORIGINAL":
                new_state = TCP_CONNTRACK_ESTABLISHED
            elif state == TCP_CONNTRACK_FIN_WAIT and direction == "REPLY":
                new_state = TCP_CONNTRACK_CLOSE_WAIT
            elif state == TCP_CONNTRACK_LAST_ACK and direction == "ORIGINAL":
                new_state = TCP_CONNTRACK_TIME_WAIT
            elif state == TCP_CONNTRACK_ESTABLISHED:
                new_state = TCP_CONNTRACK_ESTABLISHED
        elif is_fin:
            if state == TCP_CONNTRACK_ESTABLISHED:
                new_state = TCP_CONNTRACK_FIN_WAIT
            elif state == TCP_CONNTRACK_CLOSE_WAIT:
                new_state = TCP_CONNTRACK_LAST_ACK
                
        if action == "ACCEPT" and state == TCP_CONNTRACK_ESTABLISHED and strict_window_tracking:
            end = (seq + length) & 0xFFFFFFFF
            scaled_win = win << sender["scale"]
            
            valid_window = True
            if seq_gt(seq, receiver["td_maxend"]):
                valid_window = False
                reason = "OUT_OF_WINDOW_ABOVE_MAXEND"
            elif seq_lt(end, seq_diff(sender["td_end"], receiver["td_maxwin"])):
                valid_window = False
                reason = "OUT_OF_WINDOW_TOO_OLD"
            elif is_ack and seq_gt(ack, sender["td_end"]):
                valid_window = False
                reason = "INVALID_ACK_BEYOND_SENT"
                
            if not valid_window:
                action = "DROP"
                metrics["packets_dropped_invalid"] += 1
            else:
                if seq_gt(end, sender["td_end"]):
                    sender["td_end"] = end
                if is_ack and seq_gt(ack + scaled_win, receiver["td_maxend"]):
                    receiver["td_maxend"] = (ack + scaled_win) & 0xFFFFFFFF
                if scaled_win > sender["td_maxwin"]:
                    sender["td_maxwin"] = scaled_win

        if action == "ACCEPT":
            metrics["packets_accepted"] += 1
            if new_state != state:
                metrics["state_transitions"] += 1
                state = new_state
        elif action != "ACCEPT" and reason != "SYN_COOKIE_GENERATED":
            metrics["packets_dropped_invalid"] += 1

        packet_results.append({
            "pkt_id": pkt.get("id"),
            "action": action,
            "reason": reason,
            "state": state
        })

    return {
        "final_state": state,
        "metrics": metrics,
        "packet_results": packet_results,
        "conntrack_table": {
            "ORIGINAL": {
                "td_end": dirs["ORIGINAL"]["td_end"],
                "td_maxend": dirs["ORIGINAL"]["td_maxend"],
                "td_maxwin": dirs["ORIGINAL"]["td_maxwin"]
            },
            "REPLY": {
                "td_end": dirs["REPLY"]["td_end"],
                "td_maxend": dirs["REPLY"]["td_maxend"],
                "td_maxwin": dirs["REPLY"]["td_maxwin"]
            }
        }
    }

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_conntrack_tcp(data)
    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
