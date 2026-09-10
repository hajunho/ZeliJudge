import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate_tcp_memory(data):
    cfg = data.get("system_config", {})
    page_size = cfg.get("page_size_bytes", 4096)
    tcp_mem = cfg.get("tcp_mem_pages", [65536, 131072, 262144])
    tcp_rmem = cfg.get("tcp_rmem_bytes", [4096, 87380, 4194304])
    tcp_wmem = cfg.get("tcp_wmem_bytes", [4096, 16384, 4194304])
    moderate_rcvbuf = cfg.get("tcp_moderate_rcvbuf", True)

    sockets = {}
    for s in data.get("initial_sockets", []):
        sid = s["id"]
        init_rcv = s.get("rcv_buf_bytes", tcp_rmem[1])
        init_snd = s.get("snd_buf_bytes", tcp_wmem[1])
        sockets[sid] = {
            "id": sid,
            "rcv_buf_bytes": init_rcv,
            "snd_buf_bytes": init_snd,
            "ofo_bytes": s.get("ofo_bytes", 0),
            "pending_inbound_bytes": s.get("pending_inbound_bytes", 0),
            "rtt_ms": s.get("rtt_ms", 20),
            "bandwidth_mbps": s.get("bandwidth_mbps", 100),
            "advertised_window": init_rcv,
            "state": "ESTABLISHED"
        }

    pressure_state = False
    step_history = []
    total_ofo_dropped = 0
    total_skb_drops = 0
    total_conn_refusals = 0
    peak_pages = 0

    events = data.get("events", [])
    for ev in events:
        step_idx = ev.get("step", len(step_history) + 1)
        new_conns = ev.get("new_connections", [])
        traffic = ev.get("socket_traffic", {})
        closes = ev.get("socket_closes", [])

        # 1. Close sockets
        for cid in closes:
            if cid in sockets:
                del sockets[cid]

        # 2. Check current page usage
        curr_bytes = sum(s["rcv_buf_bytes"] + s["snd_buf_bytes"] + s["ofo_bytes"] for s in sockets.values())
        curr_pages = math.ceil(curr_bytes / page_size)

        # 3. New connections
        for nc in new_conns:
            sid = nc["id"]
            init_rcv = nc.get("rcv_buf_bytes", tcp_rmem[1])
            init_snd = nc.get("snd_buf_bytes", tcp_wmem[1])
            req_pages = math.ceil((init_rcv + init_snd) / page_size)

            if curr_pages + req_pages > tcp_mem[2]:
                total_conn_refusals += 1
            else:
                sockets[sid] = {
                    "id": sid,
                    "rcv_buf_bytes": init_rcv,
                    "snd_buf_bytes": init_snd,
                    "ofo_bytes": 0,
                    "pending_inbound_bytes": 0,
                    "rtt_ms": nc.get("rtt_ms", 20),
                    "bandwidth_mbps": nc.get("bandwidth_mbps", 100),
                    "advertised_window": init_rcv,
                    "state": "ESTABLISHED"
                }
                curr_bytes += init_rcv + init_snd
                curr_pages = math.ceil(curr_bytes / page_size)

        # 4. Traffic & Autotuning
        step_skb_drops = 0
        step_ofo_pruned = 0
        for sid, tr in traffic.items():
            if sid not in sockets:
                continue
            s = sockets[sid]

            d_in = tr.get("inbound_bytes", 0)
            d_out = tr.get("outbound_bytes", 0)
            d_ofo = tr.get("ofo_bytes", 0)

            if curr_pages >= tcp_mem[2]:
                step_skb_drops += 1
                total_skb_drops += 1
                continue

            s["pending_inbound_bytes"] += d_in
            s["snd_buf_bytes"] = min(tcp_wmem[2], s["snd_buf_bytes"] + d_out)
            s["ofo_bytes"] += d_ofo

            if moderate_rcvbuf and not pressure_state:
                bdp = (s["bandwidth_mbps"] * 1_000_000 / 8) * (s["rtt_ms"] / 1000)
                target = int(min(tcp_rmem[2], max(tcp_rmem[0], 2 * bdp)))
                s["rcv_buf_bytes"] = target

        # 5. Re-evaluate total memory and Pressure state
        curr_bytes = sum(s["rcv_buf_bytes"] + s["snd_buf_bytes"] + s["ofo_bytes"] for s in sockets.values())
        curr_pages = math.ceil(curr_bytes / page_size)
        peak_pages = max(peak_pages, curr_pages)

        # Hysteresis for pressure
        if curr_pages > tcp_mem[1]:
            pressure_state = True
        elif curr_pages < tcp_mem[0]:
            pressure_state = False

        status = "STATUS_NORMAL"
        zero_win_count = 0

        if curr_pages >= tcp_mem[2]:
            status = "STATUS_HARD_LIMIT_DROPPING"
        elif pressure_state:
            status = "STATUS_PRESSURE_OFO_PRUNED"

        # Apply pressure mitigations
        if pressure_state:
            for s in sockets.values():
                if s["ofo_bytes"] > 0:
                    step_ofo_pruned += s["ofo_bytes"]
                    total_ofo_dropped += s["ofo_bytes"]
                    s["ofo_bytes"] = 0

                avail_win = s["rcv_buf_bytes"] - s["pending_inbound_bytes"]
                if curr_pages >= tcp_mem[1]:
                    s["advertised_window"] = max(0, avail_win // 4)
                if s["advertised_window"] == 0:
                    zero_win_count += 1
        else:
            for s in sockets.values():
                s["advertised_window"] = max(0, s["rcv_buf_bytes"] - s["pending_inbound_bytes"])

        step_history.append({
            "step": step_idx,
            "active_sockets": len(sockets),
            "allocated_pages": curr_pages,
            "tcp_memory_pressure": pressure_state,
            "status": status,
            "ofo_pruned_bytes": step_ofo_pruned,
            "skb_drops": step_skb_drops,
            "zero_window_sockets": zero_win_count
        })

    return {
        "summary": {
            "total_steps": len(step_history),
            "peak_allocated_pages": peak_pages,
            "total_ofo_dropped_bytes": total_ofo_dropped,
            "total_skb_drops": total_skb_drops,
            "total_connection_refusals": total_conn_refusals,
            "final_pressure_state": pressure_state
        },
        "step_history": step_history
    }

def solve(data):
    return simulate_tcp_memory(data)

def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return
        data = json.loads(raw)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\\n")

if __name__ == "__main__":
    main()
