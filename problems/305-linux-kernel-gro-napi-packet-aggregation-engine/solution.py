# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #305: Linux Kernel NAPI & GRO (Generic Receive Offload) 슈퍼 패킷 집적 엔진
Linux Kernel net/core/dev.c, net/ipv4/tcp_offload.c 기반의 NAPI Polling 및 GRO 슈퍼 패킷 병합/플러시 시뮬레이션
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_gro_engine(data):
    config = data.get("config", {})
    max_gro_size = config.get("max_gro_size", 65536)
    max_gro_segs = config.get("max_gro_segs", 64)
    max_flows = config.get("max_flows", 8)
    gro_flush_interval_us = config.get("gro_flush_interval_us", 100)

    packets = data.get("packets", [])

    delivered_packets = []
    held_flows = {}
    total_coalesced = 0

    def deliver_flow(flow_key, reason):
        held = held_flows.pop(flow_key)
        flags = sorted(list(set(held["flags"])))
        delivered_packets.append({
            "flow_id": f"{held['ip']['src_ip']}:{held['tcp']['src_port']}->{held['ip']['dst_ip']}:{held['tcp']['dst_port']}",
            "start_seq": held["start_seq"],
            "end_seq": held["expected_seq"],
            "ack_seq": held["ack_seq"],
            "gso_segs": held["gso_segs"],
            "gso_size": held["gso_size"],
            "total_payload_len": held["total_payload_len"],
            "flags": flags,
            "flush_reason": reason
        })

    for pkt in packets:
        ts = pkt["timestamp_us"]
        eth = pkt.get("eth", {})
        ip = pkt.get("ip", {})
        tcp = pkt.get("tcp")
        payload_len = pkt.get("payload_len", 0)

        # 1. Check timeouts for all currently held flows
        expired_keys = [k for k, h in held_flows.items() if (ts - h["last_seen_us"]) > gro_flush_interval_us]
        expired_keys.sort(key=lambda k: (held_flows[k]["last_seen_us"], str(k)))
        for k in expired_keys:
            deliver_flow(k, "TIMEOUT")

        # 2. Control packets or Non-TCP traffic check
        is_tcp = (ip.get("proto") == "TCP") and (tcp is not None)
        ctrl_flags = {"SYN", "RST", "FIN", "URG"}
        has_ctrl = False
        if is_tcp:
            for f in tcp.get("flags", []):
                if f in ctrl_flags:
                    has_ctrl = True
                    break

        flow_key = None
        if is_tcp:
            flow_key = (
                eth.get("vlan"),
                ip.get("src_ip"),
                ip.get("dst_ip"),
                ip.get("proto"),
                tcp.get("src_port"),
                tcp.get("dst_port")
            )

        if (not is_tcp) or has_ctrl or (payload_len == 0):
            # If active flow exists for this 5-tuple, flush it first
            if flow_key and flow_key in held_flows:
                deliver_flow(flow_key, "CONTROL_PACKET")

            # Deliver this non-aggregating packet directly
            reason = "CONTROL_PACKET" if has_ctrl else "BYPASS"
            flags = sorted(list(set(tcp.get("flags", [])))) if tcp else []
            if is_tcp:
                f_id = f"{ip.get('src_ip')}:{tcp.get('src_port', 0)}->{ip.get('dst_ip')}:{tcp.get('dst_port', 0)}"
            else:
                f_id = f"{ip.get('src_ip')}->{ip.get('dst_ip')}"
            seq = tcp.get("seq", 0) if tcp else 0
            ack = tcp.get("ack_seq", 0) if tcp else 0
            delivered_packets.append({
                "flow_id": f_id,
                "start_seq": seq,
                "end_seq": seq + payload_len,
                "ack_seq": ack,
                "gso_segs": 1,
                "gso_size": payload_len,
                "total_payload_len": payload_len,
                "flags": flags,
                "flush_reason": reason
            })
            continue

        # 3. Flow matching against held flows
        if flow_key in held_flows:
            held = held_flows[flow_key]

            mac_match = (eth.get("src_mac") == held["eth"].get("src_mac")) and (eth.get("dst_mac") == held["eth"].get("dst_mac"))
            tos_match = (ip.get("tos") == held["ip"].get("tos"))

            id_match = True
            if not ip.get("df", False):
                if ip.get("id") != held["last_ip_id"] + 1:
                    id_match = False

            seq_match = (tcp.get("seq") == held["expected_seq"])
            ack_match = (tcp.get("ack_seq") >= held["ack_seq"])

            size_fits = (held["total_payload_len"] + payload_len <= max_gro_size)
            segs_fit = (held["gso_segs"] + 1 <= max_gro_segs)

            if mac_match and tos_match and id_match and seq_match and ack_match and size_fits and segs_fit:
                # Coalesce into held packet
                held["total_payload_len"] += payload_len
                held["gso_segs"] += 1
                held["expected_seq"] += payload_len
                held["last_seq"] = tcp.get("seq")
                held["last_payload_len"] = payload_len
                held["last_ip_id"] = ip.get("id")
                held["last_seen_us"] = ts
                held["ack_seq"] = max(held["ack_seq"], tcp.get("ack_seq"))
                for flg in tcp.get("flags", []):
                    if flg not in held["flags"]:
                        held["flags"].append(flg)

                total_coalesced += 1

                # Check if super-packet limit reached
                if held["total_payload_len"] >= max_gro_size:
                    deliver_flow(flow_key, "MAX_SIZE")
                elif held["gso_segs"] >= max_gro_segs:
                    deliver_flow(flow_key, "MAX_SEGS")
                continue
            else:
                # Flush existing held flow due to non-eligibility
                if not seq_match:
                    flush_reason = "OUT_OF_ORDER"
                elif not size_fits:
                    flush_reason = "MAX_SIZE"
                elif not segs_fit:
                    flush_reason = "MAX_SEGS"
                else:
                    flush_reason = "OUT_OF_ORDER"

                deliver_flow(flow_key, flush_reason)

        # 4. Table capacity check
        if len(held_flows) >= max_flows:
            oldest_key = min(held_flows.keys(), key=lambda k: (held_flows[k]["last_seen_us"], str(k)))
            deliver_flow(oldest_key, "TABLE_FULL")

        # 5. Insert incoming packet as new held flow
        held_flows[flow_key] = {
            "eth": eth,
            "ip": ip,
            "tcp": tcp,
            "start_seq": tcp.get("seq"),
            "expected_seq": tcp.get("seq") + payload_len,
            "ack_seq": tcp.get("ack_seq"),
            "gso_segs": 1,
            "gso_size": payload_len,
            "total_payload_len": payload_len,
            "flags": list(tcp.get("flags", [])),
            "last_seq": tcp.get("seq"),
            "last_payload_len": payload_len,
            "last_ip_id": ip.get("id"),
            "last_seen_us": ts
        }

    # 6. Flush remaining held flows at end of polling
    remaining_keys = sorted(held_flows.keys(), key=lambda k: (held_flows[k]["last_seen_us"], str(k)))
    for k in remaining_keys:
        deliver_flow(k, "POLL_END")

    tot_recv = len(packets)
    tot_deliv = len(delivered_packets)
    ratio = round(tot_recv / tot_deliv, 4) if tot_deliv > 0 else 0.0
    max_bytes = max([p["total_payload_len"] for p in delivered_packets], default=0)
    max_segs = max([p["gso_segs"] for p in delivered_packets], default=0)

    return {
        "summary": {
            "total_received_packets": tot_recv,
            "total_delivered_packets": tot_deliv,
            "total_gro_coalesced": total_coalesced,
            "aggregation_ratio": ratio,
            "max_super_packet_bytes": max_bytes,
            "max_super_packet_segs": max_segs
        },
        "delivered_packets": delivered_packets
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_gro_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
