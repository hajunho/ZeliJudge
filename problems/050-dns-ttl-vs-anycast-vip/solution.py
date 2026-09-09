import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    dns_ttl = 60
    hc_interval = 5
    cache_mode = "STANDARD"

    idx = 0
    while idx < len(input_data):
        line = input_data[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "DNS_TTL_SEC":
            dns_ttl = int(parts[1])
        elif parts[0] == "HEALTH_CHECK_INTERVAL_SEC":
            hc_interval = int(parts[1])
        elif parts[0] == "CLIENT_CACHE_MODE":
            cache_mode = parts[1]
        elif parts[0] == "EVENTS":
            break

    IP_TO_SERVER = {
        "192.168.1.10": "PRIMARY",
        "192.168.1.20": "BACKUP"
    }
    SERVER_TO_IP = {
        "PRIMARY": "192.168.1.10",
        "BACKUP": "192.168.1.20"
    }

    # Queue of unified simulation events
    # Orders for tie-breaking at same timestamp:
    # 0: ACTUAL server hardware/process state change
    # 1: DETECTED health check state update (t_event + hc_interval)
    # 2: REQ incoming client request
    sim_events = []

    req_count = 0
    while idx < len(input_data):
        line = input_data[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "SERVER_STATUS":
            server = parts[1]
            status = parts[2]
            t = int(parts[3])
            # Event 1: Actual change at t
            sim_events.append((t, 0, 'ACTUAL', server, status))
            # Event 2: Detected change at t + hc_interval
            sim_events.append((t + hc_interval, 1, 'DETECTED', server, status))
        elif parts[0] == "REQ":
            client_id = parts[1]
            t = int(parts[2])
            req_count += 1
            sim_events.append((t, 2, 'REQ', client_id, req_count))

    # Sort all simulation events
    sim_events.sort(key=lambda x: (x[0], x[1], x[4] if x[2] == 'REQ' else 0))

    actual_status = {
        "PRIMARY": "UP",
        "BACKUP": "UP"
    }
    detected_status = {
        "PRIMARY": "UP",
        "BACKUP": "UP"
    }

    def get_auth_dns_ip():
        if detected_status["PRIMARY"] == "UP":
            return SERVER_TO_IP["PRIMARY"]
        if detected_status["BACKUP"] == "UP":
            return SERVER_TO_IP["BACKUP"]
        return SERVER_TO_IP["PRIMARY"]

    def get_anycast_dest():
        if detected_status["PRIMARY"] == "UP":
            return "PRIMARY"
        if detected_status["BACKUP"] == "UP":
            return "BACKUP"
        return "PRIMARY"

    client_cache = {}
    total_reqs = 0
    naive_fails = 0
    anycast_fails = 0

    for ev in sim_events:
        ev_t, ev_order, ev_type = ev[0], ev[1], ev[2]

        if ev_type == 'ACTUAL':
            server, status = ev[3], ev[4]
            actual_status[server] = status
        elif ev_type == 'DETECTED':
            server, status = ev[3], ev[4]
            detected_status[server] = status
        elif ev_type == 'REQ':
            client_id = ev[3]
            total_reqs += 1

            # 1. NAIVE DNS Evaluation
            c_info = client_cache.get(client_id)
            if c_info is None or ev_t >= c_info['expires_at']:
                resolved_ip = get_auth_dns_ip()
                if cache_mode == "JVM_FOREVER":
                    exp = float('inf')
                else:
                    exp = ev_t + dns_ttl
                client_cache[client_id] = {'ip': resolved_ip, 'expires_at': exp}
            else:
                resolved_ip = c_info['ip']

            target_server = IP_TO_SERVER[resolved_ip]
            if actual_status[target_server] == "UP":
                naive_result = "SUCCESS"
            else:
                naive_result = "FAIL"
                naive_fails += 1

            # 2. ANYCAST VIP Evaluation
            routed_server = get_anycast_dest()
            if actual_status[routed_server] == "UP":
                anycast_result = "SUCCESS"
            else:
                anycast_result = "FAIL"
                anycast_fails += 1

            print(f"REQ {client_id} AT:{ev_t} NAIVE:RESOLVED={resolved_ip},RESULT={naive_result} ANYCAST:ROUTED={routed_server},RESULT={anycast_result}")

    failures_saved = naive_fails - anycast_fails
    if naive_fails > 0:
        advantage = (failures_saved / naive_fails) * 100.0
    else:
        advantage = 0.0

    print(f"SUMMARY TOTAL_REQS:{total_reqs} NAIVE_FAILURES:{naive_fails} ANYCAST_FAILURES:{anycast_fails} FAILURES_SAVED:{failures_saved} ANYCAST_RELIABILITY_ADVANTAGE:{advantage:.2f}%")

if __name__ == "__main__":
    solve()
