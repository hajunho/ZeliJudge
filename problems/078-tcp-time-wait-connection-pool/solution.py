import sys

class NaiveClient:
    def __init__(self, total_ports, time_wait_ticks, handshake_ms, request_ms):
        self.total_ports = total_ports
        self.time_wait_ticks = time_wait_ticks
        self.handshake_ms = handshake_ms
        self.request_ms = request_ms

        self.available_ports = list(range(10001, 10001 + total_ports))
        self.time_wait_sockets = {}  # port -> remaining_ticks

        self.total_requests = 0
        self.success_count = 0
        self.failed_count = 0
        self.total_latency_ms = 0

    def send_request(self):
        self.total_requests += 1

        if not self.available_ports:
            # Port exhaustion!
            self.failed_count += 1
            return "EXHAUSTED", "FAILED_(PORT_EXHAUSTED)", 0, len(self.time_wait_sockets)

        port = self.available_ports.pop(0)
        lat = self.handshake_ms + self.request_ms
        self.success_count += 1
        self.total_latency_ms += lat

        # Active close -> enters TIME_WAIT
        self.time_wait_sockets[port] = self.time_wait_ticks
        return str(port), "SUCCESS", lat, len(self.time_wait_sockets)

    def tick(self, num_ticks):
        expired = []
        for port in list(self.time_wait_sockets.keys()):
            self.time_wait_sockets[port] -= num_ticks
            if self.time_wait_sockets[port] <= 0:
                expired.append(port)
                del self.time_wait_sockets[port]

        for p in expired:
            self.available_ports.append(p)
        self.available_ports.sort()

        return len(expired), len(self.time_wait_sockets), len(self.available_ports)


class PooledClient:
    def __init__(self, pool_max_size, handshake_ms, request_ms):
        self.pool_max_size = pool_max_size
        self.handshake_ms = handshake_ms
        self.request_ms = request_ms

        self.total_conns = 0
        self.idle_conns = 0

        self.total_requests = 0
        self.success_count = 0
        self.total_latency_ms = 0

    def send_request(self):
        self.total_requests += 1

        if self.idle_conns > 0:
            # Reuse idle connection
            is_reused = True
            lat = self.request_ms
        else:
            if self.total_conns < self.pool_max_size:
                # Open new connection
                self.total_conns += 1
                is_reused = False
                lat = self.handshake_ms + self.request_ms
            else:
                # Pool full, reuse existing connection
                is_reused = True
                lat = self.request_ms

        self.success_count += 1
        self.total_latency_ms += lat

        # In pooled keep-alive, connection returns to idle immediately after request
        self.idle_conns = self.total_conns

        conn_str = "REUSED" if is_reused else "NEW"
        return conn_str, lat, self.total_conns


def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    total_ports = 50
    time_wait_ticks = 5
    handshake_ms = 20
    request_ms = 5
    pool_max_size = 10
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "TOTAL_EPHEMERAL_PORTS":
                total_ports = int(parts[1])
            elif parts[0] == "TIME_WAIT_TICKS":
                time_wait_ticks = int(parts[1])
            elif parts[0] == "HANDSHAKE_LATENCY_MS":
                handshake_ms = int(parts[1])
            elif parts[0] == "REQUEST_LATENCY_MS":
                request_ms = int(parts[1])
            elif parts[0] == "POOL_MAX_SIZE":
                pool_max_size = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    naive = NaiveClient(total_ports, time_wait_ticks, handshake_ms, request_ms)
    pooled = PooledClient(pool_max_size, handshake_ms, request_ms)

    out_lines = []

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "SEND_REQ":
            req_id = act[1]

            n_port, n_status, n_lat, n_tw = naive.send_request()
            p_conn, p_lat, p_tot_conns = pooled.send_request()

            out_lines.append(f"ACT {act_idx} SEND_REQ ID:{req_id}")
            out_lines.append(f"  NAIVE: PORT:{n_port} STATUS:{n_status} LATENCY:{n_lat}ms TIME_WAIT_SOCKETS:{n_tw}")
            out_lines.append(f"  POOLED: CONN:{p_conn} STATUS:SUCCESS LATENCY:{p_lat}ms POOL_CONNS:{p_tot_conns}/{pool_max_size} TIME_WAIT_SOCKETS:0")

        elif cmd == "TICK":
            ticks = int(act[1])
            exp_tw, rem_tw, avail_p = naive.tick(ticks)
            out_lines.append(f"ACT {act_idx} TICK {ticks}")
            out_lines.append(f"  NAIVE: EXPIRED_TIME_WAIT:{exp_tw} REMAINING_TIME_WAIT:{rem_tw} AVAILABLE_PORTS:{avail_p}/{total_ports}")

        elif cmd == "CHECK_METRICS":
            out_lines.append(f"ACT {act_idx} CHECK_METRICS")
            out_lines.append(f"  NAIVE: TOTAL:{naive.total_requests} SUCCESS:{naive.success_count} FAILED:{naive.failed_count} TOTAL_LATENCY:{naive.total_latency_ms}ms TIME_WAIT_ACTIVE:{len(naive.time_wait_sockets)}")
            out_lines.append(f"  POOLED: TOTAL:{pooled.total_requests} SUCCESS:{pooled.success_count} FAILED:0 TOTAL_LATENCY:{pooled.total_latency_ms}ms POOL_CONNS:{pooled.total_conns}/{pool_max_size}")

    n_fail_rate = (naive.failed_count / naive.total_requests * 100.0) if naive.total_requests > 0 else 0.0
    saved_lat = naive.total_latency_ms - pooled.total_latency_ms
    lat_red = (saved_lat / naive.total_latency_ms * 100.0) if naive.total_latency_ms > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_HTTP_REQUESTS:{naive.total_requests}")
    out_lines.append(f"SUMMARY NAIVE SUCCESS:{naive.success_count} FAILED:{naive.failed_count} FAILURE_RATE:{n_fail_rate:.2f}% TOTAL_LATENCY:{naive.total_latency_ms}ms")
    out_lines.append(f"SUMMARY POOLED SUCCESS:{pooled.success_count} FAILED:0 FAILURE_RATE:0.00% TOTAL_LATENCY:{pooled.total_latency_ms}ms")
    out_lines.append(f"SUMMARY LATENCY_SAVED:{saved_lat}ms (LATENCY_REDUCTION:{lat_red:.2f}%)")
    out_lines.append("SUMMARY SOCKET_STABILITY: POOLING_PREVENTS_TIME_WAIT_EXHAUSTION")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
