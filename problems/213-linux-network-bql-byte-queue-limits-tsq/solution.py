import sys
import json
from collections import defaultdict, deque

def simulate_bql_tsq(data):
    config = data.get("config", {})
    mode = config.get("mode", "OPTIMAL_BQL_AND_TSQ_PACING")
    link_speed_mbps = config.get("link_speed_mbps", 1000)
    bytes_per_ms = (link_speed_mbps * 1_000_000) / (8 * 1000)

    mss_bytes = config.get("mss_bytes", 1500)
    tx_ring_max_descriptors = config.get("tx_ring_max_descriptors", 4096)
    hw_ring_max_bytes = tx_ring_max_descriptors * mss_bytes

    bql_enabled = ("BQL" in mode) and ("NO_BQL" not in mode)
    tsq_enabled = ("TSQ" in mode) and ("NO_TSQ" not in mode)

    bql_min_limit = config.get("bql_min_limit_bytes", 3000)
    bql_max_limit = config.get("bql_max_limit_bytes", 30000)
    bql_initial_limit = config.get("bql_initial_limit_bytes", 6000)
    bql_current_limit = bql_initial_limit

    tsq_limit_bytes = config.get("tsq_limit_bytes", 3000)
    tx_interrupt_interval_ms = config.get("tx_interrupt_interval_ms", 0.1)

    events = sorted(data.get("events", []), key=lambda x: x["timestamp_ms"])

    socket_write_queue = defaultdict(deque)
    socket_wmem_alloc = defaultdict(int)
    qdisc_queue = deque()
    driver_ring = deque()
    bytes_in_driver_ring = 0

    metrics = {
        "total_packets_sent": len(events),
        "total_bytes_transmitted": 0,
        "bulk_packets_transmitted": 0,
        "interactive_packets_transmitted": 0,
        "max_driver_queue_bytes": 0,
        "max_driver_queue_latency_ms": 0.0,
        "average_bulk_latency_ms": 0.0,
        "average_interactive_latency_ms": 0.0,
        "tsq_throttled_packets": 0,
        "bql_backpressure_events": 0,
        "line_rate_utilization_pct": 0.0
    }

    bulk_latencies = []
    interactive_latencies = []
    driver_latencies = []

    dt_ms = 0.05
    max_event_time = max([e["timestamp_ms"] for e in events]) if events else 0.0
    current_time_ms = 0.0
    ev_idx = 0
    n_events = len(events)
    last_interrupt_time = 0.0

    busy_time_ms = 0.0
    total_active_duration_ms = 0.0

    def try_push_socket_to_qdisc():
        active_flows = [fid for fid in socket_write_queue if socket_write_queue[fid]]
        for fid in active_flows:
            while socket_write_queue[fid]:
                pkt = socket_write_queue[fid][0]
                if tsq_enabled:
                    if socket_wmem_alloc[fid] + pkt["size"] > tsq_limit_bytes:
                        metrics["tsq_throttled_packets"] += 1
                        break
                socket_write_queue[fid].popleft()
                socket_wmem_alloc[fid] += pkt["size"]
                if tsq_enabled and pkt["is_interactive"]:
                    qdisc_queue.appendleft(pkt)
                else:
                    qdisc_queue.append(pkt)

    def try_push_qdisc_to_driver():
        nonlocal bytes_in_driver_ring
        effective_limit = bql_current_limit if bql_enabled else hw_ring_max_bytes
        while qdisc_queue:
            pkt = qdisc_queue[0]
            if bytes_in_driver_ring + pkt["size"] <= effective_limit:
                qdisc_queue.popleft()
                pkt["enqueued_driver_time"] = current_time_ms
                driver_ring.append(pkt)
                bytes_in_driver_ring += pkt["size"]
                if bytes_in_driver_ring > metrics["max_driver_queue_bytes"]:
                    metrics["max_driver_queue_bytes"] = bytes_in_driver_ring
            else:
                if bql_enabled:
                    metrics["bql_backpressure_events"] += 1
                break

    while current_time_ms <= max_event_time + 100.0 or driver_ring or qdisc_queue or any(socket_write_queue.values()):
        if current_time_ms > max_event_time + 500.0:
            break

        while ev_idx < n_events and events[ev_idx]["timestamp_ms"] <= current_time_ms:
            ev = events[ev_idx]
            ev_idx += 1
            fid = ev["flow_id"]
            pkt = {
                "packet_id": ev.get("packet_id", ev_idx),
                "flow_id": fid,
                "size": ev.get("size", mss_bytes),
                "created_time": ev["timestamp_ms"],
                "is_interactive": ev.get("is_interactive", False)
            }
            socket_write_queue[fid].append(pkt)

        try_push_socket_to_qdisc()
        try_push_qdisc_to_driver()

        transmittable = bytes_per_ms * dt_ms
        has_transmitted = False

        while driver_ring and transmittable > 0:
            has_transmitted = True
            pkt = driver_ring[0]
            if pkt["size"] <= transmittable:
                transmittable -= pkt["size"]
                driver_ring.popleft()
                bytes_in_driver_ring -= pkt["size"]
                socket_wmem_alloc[pkt["flow_id"]] = max(0, socket_wmem_alloc[pkt["flow_id"]] - pkt["size"])
                metrics["total_bytes_transmitted"] += pkt["size"]

                drv_lat = current_time_ms - pkt["enqueued_driver_time"]
                driver_latencies.append(drv_lat)

                e2e_lat = current_time_ms - pkt["created_time"]
                if pkt["is_interactive"]:
                    metrics["interactive_packets_transmitted"] += 1
                    interactive_latencies.append(e2e_lat)
                else:
                    metrics["bulk_packets_transmitted"] += 1
                    bulk_latencies.append(e2e_lat)
            else:
                pkt["size"] -= transmittable
                bytes_in_driver_ring -= transmittable
                socket_wmem_alloc[pkt["flow_id"]] = max(0, socket_wmem_alloc[pkt["flow_id"]] - transmittable)
                metrics["total_bytes_transmitted"] += transmittable
                transmittable = 0

        if has_transmitted or bytes_in_driver_ring > 0:
            busy_time_ms += dt_ms
        total_active_duration_ms += dt_ms

        if current_time_ms - last_interrupt_time >= tx_interrupt_interval_ms:
            last_interrupt_time = current_time_ms
            try_push_socket_to_qdisc()
            try_push_qdisc_to_driver()

            if bql_enabled:
                if bytes_in_driver_ring == 0:
                    bql_current_limit = min(bql_max_limit, bql_current_limit + mss_bytes)
                elif bytes_in_driver_ring > bql_current_limit:
                    bql_current_limit = max(bql_min_limit, bql_current_limit - mss_bytes)

        current_time_ms += dt_ms

    avg_bulk = (sum(bulk_latencies) / len(bulk_latencies)) if bulk_latencies else 0.0
    avg_interactive = (sum(interactive_latencies) / len(interactive_latencies)) if interactive_latencies else 0.0
    max_drv_lat = max(driver_latencies) if driver_latencies else 0.0
    utilization = (busy_time_ms / total_active_duration_ms * 100.0) if total_active_duration_ms > 0 else 100.0

    metrics["average_bulk_latency_ms"] = round(avg_bulk, 2)
    metrics["average_interactive_latency_ms"] = round(avg_interactive, 2)
    metrics["max_driver_queue_latency_ms"] = round(max_drv_lat, 2)
    metrics["line_rate_utilization_pct"] = round(min(100.0, utilization), 1)

    if metrics["max_driver_queue_bytes"] > 50000 or metrics["max_driver_queue_latency_ms"] > 10.0:
        verdict = "BUFFERBLOAT_DRIVER_RING_EXPLOSION"
        status = "FAILED"
    elif mode == "BQL_ONLY":
        if metrics["average_interactive_latency_ms"] > 15.0:
            verdict = "BQL_DEVICE_CLAMPED_BUT_QDISC_BLOAT"
            status = "FAILED"
        else:
            verdict = "BQL_DRIVER_QUEUE_CLAMPED"
            status = "SUCCESS"
    elif mode in ("OPTIMAL_BQL_AND_TSQ_PACING", "BQL_AND_TSQ_OPTIMAL"):
        if metrics["total_packets_sent"] < 10:
            verdict = "LIGHT_TRAFFIC_CLEAN_FLOW"
            status = "SUCCESS"
        else:
            verdict = "OPTIMAL_BQL_AND_TSQ_PACING"
            status = "SUCCESS"
    else:
        verdict = "LIGHT_TRAFFIC_CLEAN_FLOW"
        status = "SUCCESS"

    return {
        "status": status,
        "verdict": verdict,
        "mode": mode,
        "metrics": metrics
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_bql_tsq(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
