# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #293: Linux Kernel GRO (Generic Receive Offload) NAPI Aggregation
https://github.com/hajunho/ZeliJudge
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

MAX_GRO_SIZE = 65536

class GROFlow:
    def __init__(self, key, first_pkt, time_us):
        self.key = key  # (src_ip, dst_ip, src_port, dst_port, protocol)
        self.first_time_us = time_us
        self.last_time_us = time_us
        self.start_seq = first_pkt.get("tcp_seq", 0)
        payload_len = first_pkt.get("payload_len", 0)
        self.next_seq = self.start_seq + payload_len
        self.total_payload_bytes = payload_len
        self.total_wire_bytes = first_pkt.get("wire_len", 1514)
        self.packet_count = 1
        flags = first_pkt.get("flags", ["ACK"])
        self.ack_count = 1 if payload_len == 0 and "ACK" in flags else 0
        self.last_ack_num = first_pkt.get("tcp_ack", 0)
        self.is_pure_ack = (payload_len == 0)

def simulate_gro(config, events):
    gro_max_size = config.get("gro_max_size", MAX_GRO_SIZE)
    gro_flush_timeout_us = config.get("gro_flush_timeout_us", 50.0)
    ack_compression_enabled = config.get("ack_compression_enabled", True)

    active_flows = {}  # key -> GROFlow
    flushed_packets = []

    total_rx_packets = 0
    total_rx_bytes = 0

    flush_counts = {
        "OUT_OF_ORDER": 0,
        "SPECIAL_FLAG": 0,
        "SIZE_LIMIT": 0,
        "TIMEOUT": 0,
        "NAPI_CYCLE_END": 0
    }

    def flush_flow(key, reason):
        flow = active_flows.pop(key, None)
        if not flow:
            return
        flush_counts[reason] = flush_counts.get(reason, 0) + 1
        flushed_packets.append({
            "flow_id": f"{flow.key[0]}:{flow.key[2]}->{flow.key[1]}:{flow.key[3]}",
            "packet_count": flow.packet_count,
            "payload_bytes": flow.total_payload_bytes,
            "wire_bytes": flow.total_wire_bytes,
            "start_seq": flow.start_seq,
            "end_seq": flow.next_seq,
            "duration_us": round(flow.last_time_us - flow.first_time_us, 2),
            "flush_reason": reason,
            "ack_compressed_count": flow.ack_count
        })

    for ev in events:
        ev_type = ev.get("type", "RX")
        time_us = ev.get("time_us", 0.0)

        if ev_type == "NAPI_CYCLE_END":
            # Flush all active flows deterministically by (first_time_us, key)
            keys = sorted(active_flows.keys(), key=lambda k: (active_flows[k].first_time_us, k))
            for k in keys:
                flush_flow(k, "NAPI_CYCLE_END")
            continue

        if ev_type == "RX":
            pkt = ev.get("packet", {})
            total_rx_packets += 1
            wire_len = pkt.get("wire_len", 1514)
            total_rx_bytes += wire_len

            key = (
                pkt.get("src_ip", "10.0.0.1"),
                pkt.get("dst_ip", "10.0.0.2"),
                pkt.get("src_port", 5000),
                pkt.get("dst_port", 80),
                pkt.get("protocol", "TCP")
            )

            flags = pkt.get("flags", ["ACK"])
            payload_len = pkt.get("payload_len", 1460)
            seq = pkt.get("tcp_seq", 0)
            ack = pkt.get("tcp_ack", 0)

            # Check special flags (SYN, FIN, RST)
            has_special_flag = any(f in flags for f in ["SYN", "FIN", "RST"])
            if has_special_flag:
                if key in active_flows:
                    flush_flow(key, "SPECIAL_FLAG")
                # Immediately emit the special flag packet as a single flushed packet
                active_flows[key] = GROFlow(key, pkt, time_us)
                flush_flow(key, "SPECIAL_FLAG")
                continue

            # If flow is not currently active, initialize it
            if key not in active_flows:
                active_flows[key] = GROFlow(key, pkt, time_us)
                continue

            flow = active_flows[key]

            # 1. Check timeout
            if (time_us - flow.first_time_us) >= gro_flush_timeout_us:
                flush_flow(key, "TIMEOUT")
                active_flows[key] = GROFlow(key, pkt, time_us)
                continue

            # 2. Check pure ACK vs Data Packet mismatch
            incoming_is_pure_ack = (payload_len == 0 and "ACK" in flags)
            if flow.is_pure_ack != incoming_is_pure_ack:
                flush_flow(key, "OUT_OF_ORDER")
                active_flows[key] = GROFlow(key, pkt, time_us)
                continue

            # 3. Check sequence continuity / ACK continuity
            if flow.is_pure_ack:
                if ack_compression_enabled:
                    if ack < flow.last_ack_num:
                        # Non-monotonic ACK regression
                        flush_flow(key, "OUT_OF_ORDER")
                        active_flows[key] = GROFlow(key, pkt, time_us)
                        continue
                else:
                    flush_flow(key, "OUT_OF_ORDER")
                    active_flows[key] = GROFlow(key, pkt, time_us)
                    continue
            else:
                # Data packet sequence check
                if seq != flow.next_seq:
                    # Out-of-order sequence
                    flush_flow(key, "OUT_OF_ORDER")
                    active_flows[key] = GROFlow(key, pkt, time_us)
                    continue

            # 4. Check size limit
            if (flow.total_payload_bytes + payload_len) > gro_max_size:
                flush_flow(key, "SIZE_LIMIT")
                active_flows[key] = GROFlow(key, pkt, time_us)
                continue

            # 5. Coalesce packet into current flow
            flow.packet_count += 1
            flow.total_payload_bytes += payload_len
            flow.total_wire_bytes += wire_len
            flow.next_seq = seq + payload_len
            flow.last_time_us = time_us
            flow.last_ack_num = ack
            if incoming_is_pure_ack:
                flow.ack_count += 1

    # End of simulation: flush any lingering active flows
    keys = sorted(active_flows.keys(), key=lambda k: (active_flows[k].first_time_us, k))
    for k in keys:
        flush_flow(k, "NAPI_CYCLE_END")

    num_flushed = len(flushed_packets)
    agg_ratio = round(total_rx_packets / max(1, num_flushed), 2)
    reduction_pct = round((1.0 - (num_flushed / max(1, total_rx_packets))) * 100.0, 2)

    # Health & Bottleneck diagnostics
    anomalies = []
    status = "OPTIMAL_GRO_AGGREGATION"
    collapse_detected = False

    ooo_count = flush_counts.get("OUT_OF_ORDER", 0)
    if num_flushed > 0 and ooo_count / num_flushed > 0.25:
        collapse_detected = True
        anomalies.append("HIGH_OUT_OF_ORDER_RATE_GRO_COLLAPSE")
        status = "GRO_COLLAPSED"
    elif agg_ratio < 2.0 and total_rx_packets >= 10:
        anomalies.append("LOW_AGGREGATION_EFFICIENCY")
        status = "SUBOPTIMAL_GRO"

    if flush_counts.get("TIMEOUT", 0) > 0 and agg_ratio < 4.0:
        anomalies.append("FREQUENT_TIMEOUT_FLUSH")

    return {
        "flushed_super_packets": flushed_packets,
        "metrics": {
            "total_rx_packets": total_rx_packets,
            "total_rx_bytes": total_rx_bytes,
            "flushed_super_packets_count": num_flushed,
            "aggregation_ratio": agg_ratio,
            "packet_reduction_pct": reduction_pct,
            "flush_reasons": flush_counts
        },
        "diagnostics": {
            "status": status,
            "collapse_detected": collapse_detected,
            "anomalies": anomalies
        }
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    config = data.get("config", {})
    events = data.get("traffic_events", [])
    result = simulate_gro(config, events)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
