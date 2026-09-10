import hashlib
import hmac
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

def generate_tfo_cookie(key: str, client_ip: str) -> str:
    h = hmac.new(key.encode('utf-8'), client_ip.encode('utf-8'), hashlib.sha256)
    return h.hexdigest()[:16]

def simulate():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
        
    payload = json.loads(raw_data)
    config = payload.get("config", {})
    initial_state = payload.get("initial_state", {})
    events = payload.get("events", [])
    
    server_primary_key = config.get("server_primary_key", "secr3t_k3y_pr1mary")
    server_backup_key = config.get("server_backup_key", None)
    max_qlen = int(config.get("max_fastopen_queue", 10))
    blackhole_threshold = int(config.get("blackhole_threshold", 2))
    
    cur_qlen = int(initial_state.get("current_queue_len", 0))
    client_cache = dict(initial_state.get("client_cookie_cache", {}))
    blackhole_failures = int(initial_state.get("consecutive_drops", 0))
    tfo_disabled = bool(initial_state.get("tfo_disabled", False))
    
    active_tfo_connections = set()
    history = []
    
    total_0rtt_bytes = 0
    total_0rtt_successes = 0
    total_fallbacks = 0
    total_syn_floods_mitigated = 0
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        status = "OK"
        detail = ""
        
        if ev_type == "ROTATE_SERVER_KEY":
            new_key = ev_params.get("new_key", "new_secr3t_k3y")
            server_backup_key = server_primary_key
            server_primary_key = new_key
            status = "KEY_ROTATED"
            detail = f"Primary key rotated to {new_key[:8]}..., backup retained"
            
        elif ev_type == "COOKIE_REQUEST":
            client_ip = ev_params.get("client_ip", "10.0.0.1")
            new_cookie = generate_tfo_cookie(server_primary_key, client_ip)
            client_cache[client_ip] = new_cookie
            status = "COOKIE_ISSUED"
            detail = f"Cookie {new_cookie} issued to {client_ip}"
            
        elif ev_type == "SYN_DATA_TRANSMIT":
            conn_id = ev_params.get("conn_id", f"conn_{ep_idx}")
            client_ip = ev_params.get("client_ip", "10.0.0.1")
            data_len = int(ev_params.get("data_bytes", 1460))
            is_dropped = bool(ev_params.get("network_drop", False))
            
            if tfo_disabled:
                total_fallbacks += 1
                status = "FALLBACK_TFO_DISABLED"
                detail = f"TFO disabled on client due to blackhole. Sent regular SYN."
            elif is_dropped:
                blackhole_failures += 1
                if blackhole_failures >= blackhole_threshold:
                    tfo_disabled = True
                status = "SYN_DATA_DROPPED"
                detail = f"Middlebox dropped SYN+Data. Blackhole count={blackhole_failures}."
            else:
                blackhole_failures = 0
                provided_cookie = client_cache.get(client_ip, "")
                expected_primary = generate_tfo_cookie(server_primary_key, client_ip)
                expected_backup = generate_tfo_cookie(server_backup_key, client_ip) if server_backup_key else None
                
                is_valid = (provided_cookie == expected_primary)
                is_backup_valid = (server_backup_key and provided_cookie == expected_backup)
                
                if not is_valid and not is_backup_valid:
                    fresh_cookie = generate_tfo_cookie(server_primary_key, client_ip)
                    client_cache[client_ip] = fresh_cookie
                    total_fallbacks += 1
                    status = "FALLBACK_INVALID_COOKIE"
                    detail = f"Cookie mismatch. New cookie issued; fallback to standard 3WHS."
                elif cur_qlen >= max_qlen:
                    total_syn_floods_mitigated += 1
                    total_fallbacks += 1
                    status = "FALLBACK_QUEUE_FULL"
                    detail = f"TFO queue full ({cur_qlen}/{max_qlen}). Fallback to 3WHS without queuing data."
                else:
                    cur_qlen += 1
                    active_tfo_connections.add(conn_id)
                    total_0rtt_successes += 1
                    total_0rtt_bytes += data_len
                    
                    if is_backup_valid:
                        fresh_cookie = generate_tfo_cookie(server_primary_key, client_ip)
                        client_cache[client_ip] = fresh_cookie
                        status = "TFO_0RTT_SUCCESS_BACKUP_KEY"
                        detail = f"Accepted via backup key. Data {data_len}B processed; refreshed to primary cookie."
                    else:
                        status = "TFO_0RTT_SUCCESS"
                        detail = f"0-RTT success. Data {data_len}B delivered to socket immediately."
                        
        elif ev_type == "COMPLETE_HANDSHAKE":
            conn_id = ev_params.get("conn_id", "")
            if conn_id in active_tfo_connections:
                active_tfo_connections.remove(conn_id)
                cur_qlen = max(0, cur_qlen - 1)
                status = "HANDSHAKE_COMPLETED_TFO"
                detail = f"Connection {conn_id} completed 3WHS. TFO queue decremented to {cur_qlen}."
            else:
                status = "HANDSHAKE_COMPLETED_REGULAR"
                detail = f"Connection {conn_id} standard handshake completed."
                
        elif ev_type == "CLIENT_PROBE_RESTORE":
            client_ip = ev_params.get("client_ip", "10.0.0.1")
            probe_success = bool(ev_params.get("probe_success", True))
            if probe_success:
                tfo_disabled = False
                blackhole_failures = 0
                status = "TFO_RESTORED"
                detail = "Path probe succeeded. TFO re-enabled."
            else:
                status = "TFO_STILL_DISABLED"
                detail = "Path probe failed. TFO remains disabled."
                
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "status": status,
            "current_queue_len": cur_qlen,
            "tfo_disabled": tfo_disabled,
            "blackhole_failures": blackhole_failures,
            "detail": detail
        })
        
    result = {
        "final_queue_len": cur_qlen,
        "tfo_disabled": tfo_disabled,
        "total_0rtt_successes": total_0rtt_successes,
        "total_0rtt_bytes": total_0rtt_bytes,
        "total_fallbacks": total_fallbacks,
        "total_syn_floods_mitigated": total_syn_floods_mitigated,
        "client_cookie_cache": client_cache,
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
