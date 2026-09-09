import json
import sys

def solve(data):
    fw_cfg = data.get("firewall_config", {})
    idle_timeout = float(fw_cfg.get("idle_timeout_seconds", 60.0))
    
    hb_cfg = data.get("heartbeat_config", {})
    mode = hb_cfg.get("mode", "NONE").upper()
    ping_interval = float(hb_cfg.get("ping_interval_seconds", 25.0))
    pong_timeout = float(hb_cfg.get("pong_timeout_seconds", 10.0))
    max_missed_pongs = int(hb_cfg.get("max_missed_pongs", 2))
    
    net_profile = data.get("network_profile", {})
    proxy_type = net_profile.get("proxy_type", "L7_REVERSE_PROXY").upper()
    network_severed_at = net_profile.get("network_severed_at_second", None)
    if network_severed_at is not None:
        network_severed_at = float(network_severed_at)
        
    user_events = data.get("user_events", [])
    
    # Simulation timeline
    # Generate all discrete events:
    # 1. USER_MSG at specified times
    # 2. PING at ping_interval intervals (if WEBSOCKET_PING_PONG)
    # 3. TCP_KEEPALIVE (if TCP_KEEPALIVE)
    
    max_time = 0.0
    for ue in user_events:
        max_time = max(max_time, float(ue.get("time_seconds", 0.0)))
    max_time = max(max_time + 10.0, 150.0)
    
    timeline = []
    for ue in user_events:
        t = float(ue.get("time_seconds", 0.0))
        timeline.append((t, "USER_MSG", ue.get("payload", "")))
        
    if mode == "WEBSOCKET_PING_PONG":
        t = ping_interval
        while t <= max_time:
            timeline.append((t, "WS_PING", "PING"))
            t += ping_interval
            
    elif mode == "TCP_KEEPALIVE":
        # TCP Keep alive interval (typically 30s if tuned, but let's see if it passes proxy)
        t = ping_interval
        while t <= max_time:
            timeline.append((t, "TCP_KEEPALIVE", "KEEPALIVE"))
            t += ping_interval
            
    timeline.sort(key=lambda x: x[0])
    
    conntrack_last_activity = 0.0
    conntrack_alive = True
    conntrack_died_at = None
    
    client_alive = True
    client_detected_close_at = None
    
    silent_drop_occurred = False
    zombie_duration = 0.0
    
    messages_sent = 0
    messages_delivered = 0
    
    missed_pongs = 0
    
    for t, ev_type, payload in timeline:
        if not client_alive:
            break
            
        # Check conntrack timeout before this event
        if conntrack_alive:
            if (t - conntrack_last_activity) >= idle_timeout:
                # Firewall quietly drops conntrack entry without telling client or server!
                conntrack_alive = False
                conntrack_died_at = conntrack_last_activity + idle_timeout
                
        # Check if physical network was severed before this
        physically_connected = True
        if network_severed_at is not None and t >= network_severed_at:
            physically_connected = False
            
        if ev_type == "USER_MSG":
            messages_sent += 1
            if not physically_connected:
                # Message cannot reach, RST or timeout
                client_alive = False
                client_detected_close_at = t
            elif not conntrack_alive:
                # Silent drop occurred previously! Firewall returns RST now
                silent_drop_occurred = True
                client_alive = False
                client_detected_close_at = t
                if conntrack_died_at is not None:
                    zombie_duration = max(zombie_duration, t - conntrack_died_at)
            else:
                # Delivered!
                messages_delivered += 1
                conntrack_last_activity = t
                
        elif ev_type == "WS_PING":
            if not physically_connected:
                missed_pongs += 1
                if missed_pongs >= max_missed_pongs:
                    client_alive = False
                    client_detected_close_at = t + pong_timeout
            elif not conntrack_alive:
                # Firewall dropped conntrack -> RST received on ping attempt!
                silent_drop_occurred = True
                client_alive = False
                client_detected_close_at = t
                if conntrack_died_at is not None:
                    zombie_duration = max(zombie_duration, t - conntrack_died_at)
            else:
                # Ping reaches server through any proxy, Pong returns!
                conntrack_last_activity = t
                missed_pongs = 0
                
        elif ev_type == "TCP_KEEPALIVE":
            if proxy_type == "L7_REVERSE_PROXY":
                # TCP KeepAlive is absorbed by client-side proxy and does NOT refresh firewall conntrack!
                pass
            else:
                # L4 transparent: refreshes conntrack
                if physically_connected and conntrack_alive:
                    conntrack_last_activity = t

    # Final verdict
    if silent_drop_occurred and mode == "NONE":
        verdict = "SILENT_DROP_DISASTER"
    elif silent_drop_occurred and mode == "TCP_KEEPALIVE" and proxy_type == "L7_REVERSE_PROXY":
        verdict = "TCP_KEEPALIVE_L7_PROXY_BYPASS_FAILURE"
    elif mode == "WEBSOCKET_PING_PONG" and messages_delivered == messages_sent and not silent_drop_occurred:
        verdict = "WEBSOCKET_PING_PONG_RESILIENT"
    elif not client_alive and network_severed_at is not None:
        verdict = "NETWORK_SEVERED_PROMPTLY_DETECTED"
    else:
        verdict = "BALANCED_EXECUTION"
        
    summary = {
        "heartbeat_mode": mode,
        "firewall_idle_timeout_seconds": idle_timeout,
        "proxy_type": proxy_type,
        "conntrack_alive_at_end": conntrack_alive,
        "client_connected_at_end": client_alive,
        "silent_drop_occurred": silent_drop_occurred,
        "zombie_duration_seconds": round(zombie_duration, 2),
        "user_messages_sent": messages_sent,
        "user_messages_delivered": messages_delivered,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
