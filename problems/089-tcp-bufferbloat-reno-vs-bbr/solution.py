import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    bandwidth = 5
    buffer_capacity = 20
    base_rtt = 2
    initial_ssthresh = 16
    actions = []
    mode = "CONFIG"

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
            if parts[0] == "BANDWIDTH":
                bandwidth = int(parts[1])
            elif parts[0] == "BUFFER_CAPACITY":
                buffer_capacity = int(parts[1])
            elif parts[0] == "BASE_RTT":
                base_rtt = int(parts[1])
            elif parts[0] == "INITIAL_SSTHRESH":
                initial_ssthresh = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    cwnd = 1.0
    ssthresh = initial_ssthresh
    reno_queue = 0
    total_drops = 0
    reno_latencies = []
    bbr_latencies = []

    out_lines = []
    act_idx = 1

    for act in actions:
        cmd = act[0]

        if cmd == "STEP":
            bdp = bandwidth * base_rtt
            inflight = int(cwnd)
            raw_queue = max(0, inflight - bdp)

            if raw_queue > buffer_capacity:
                drops = raw_queue - buffer_capacity
                reno_queue = buffer_capacity
                total_drops += drops
                ssthresh = max(2, int(cwnd) // 2)
                next_cwnd = float(ssthresh)
            else:
                drops = 0
                reno_queue = raw_queue
                if cwnd < ssthresh:
                    next_cwnd = min(float(ssthresh), cwnd * 2.0)
                else:
                    next_cwnd = cwnd + 1.0

            reno_lat = base_rtt + (reno_queue / bandwidth)
            reno_latencies.append(reno_lat)
            cur_cwnd_int = int(cwnd)
            cwnd = next_cwnd

            bbr_cwnd = bdp
            bbr_queue = 0
            bbr_drops = 0
            bbr_lat = float(base_rtt)
            bbr_latencies.append(bbr_lat)

            out_lines.append(f"ACT {act_idx} STEP RENO:[CWND:{cur_cwnd_int} QUEUE:{reno_queue} DROPS:{drops} LATENCY:{reno_lat:.1f}] BBR:[CWND:{bbr_cwnd} QUEUE:{bbr_queue} DROPS:{bbr_drops} LATENCY:{bbr_lat:.1f}]")

        elif cmd == "PING":
            pid = act[1]
            r_lat = base_rtt + (reno_queue / bandwidth)
            b_lat = float(base_rtt)
            ratio = r_lat / b_lat if b_lat > 0 else 1.0
            out_lines.append(f"ACT {act_idx} PING {pid} RENO_LATENCY:{r_lat:.1f} BBR_LATENCY:{b_lat:.1f} (BBR_FASTER:{ratio:.2f}x)")

        elif cmd == "SET_BANDWIDTH":
            bandwidth = int(act[1])
            new_bdp = bandwidth * base_rtt
            out_lines.append(f"ACT {act_idx} SET_BANDWIDTH NEW_BW:{bandwidth} NEW_BDP:{new_bdp}")

        act_idx += 1

    reno_avg = sum(reno_latencies) / len(reno_latencies) if reno_latencies else float(base_rtt)
    reno_max = max(reno_latencies) if reno_latencies else float(base_rtt)
    bbr_avg = sum(bbr_latencies) / len(bbr_latencies) if bbr_latencies else float(base_rtt)
    bbr_max = max(bbr_latencies) if bbr_latencies else float(base_rtt)

    is_bloat = "TRUE" if reno_max >= base_rtt * 1.5 else "FALSE"
    reduction = (reno_avg - bbr_avg) / reno_avg * 100.0 if reno_avg > 0 else 0.0
    inflation = (reno_max - base_rtt) / base_rtt * 100.0 if base_rtt > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_ACTIONS:{len(actions)}")
    out_lines.append(f"SUMMARY RENO TOTAL_DROPS:{total_drops} AVG_LATENCY:{reno_avg:.2f} MAX_LATENCY:{reno_max:.2f} BUFFERBLOAT:{is_bloat}")
    out_lines.append(f"SUMMARY BBR TOTAL_DROPS:0 AVG_LATENCY:{bbr_avg:.2f} MAX_LATENCY:{bbr_max:.2f} BUFFERBLOAT:FALSE")
    out_lines.append(f"SUMMARY AVG_LATENCY_REDUCTION:{reduction:.1f}%")
    out_lines.append(f"SUMMARY MAX_BUFFERBLOAT_INFLATION:{inflation:.1f}%")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
