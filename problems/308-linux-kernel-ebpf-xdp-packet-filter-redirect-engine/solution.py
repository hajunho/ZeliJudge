# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #308: 리눅스 커널 eBPF XDP(eXpress Data Path) 고속 패킷 필터 및 제로카피 리다이렉트 엔진
Linux Kernel net/core/filter.c, include/uapi/linux/bpf.h 기반의 XDP 5대 액션
(XDP_ABORTED, XDP_DROP, XDP_PASS, XDP_TX, XDP_REDIRECT), AF_XDP 커널 바이패스,
DEVMAP/CPUMAP 패킷 포워딩 및 L2/L3 헤더 재작성 시뮬레이션
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_xdp_engine(data):
    config = data.get("config", {})
    interfaces = {i["ifindex"]: i for i in config.get("interfaces", [])}
    cpu_cores = config.get("cpu_cores", 4)

    bpf_maps = data.get("bpf_maps", {})
    blacklist = set(bpf_maps.get("blacklist_ips", []))
    devmap = bpf_maps.get("devmap", {})
    xskmap = set(bpf_maps.get("xskmap", []))
    cpumap_enabled = bpf_maps.get("cpumap_hash_enabled", False)

    packets = data.get("packets", [])

    action_counts = {
        "XDP_ABORTED": 0,
        "XDP_DROP": 0,
        "XDP_PASS": 0,
        "XDP_TX": 0,
        "XDP_REDIRECT": 0
    }

    packet_results = []

    for pkt in packets:
        p_id = pkt["pkt_id"]
        rx_if = pkt["rx_ifindex"]
        rx_cpu = pkt["rx_cpu"]
        eth = dict(pkt.get("eth", {}))
        ip = dict(pkt.get("ip", {}))
        l4 = dict(pkt.get("l4", {})) if pkt.get("l4") else None
        corrupted = pkt.get("corrupted_bounds", False)

        # 1. Bounds check: Verifier safety constraint violation
        if corrupted:
            action = "XDP_ABORTED"
            action_counts[action] += 1
            packet_results.append({
                "pkt_id": p_id,
                "action": action,
                "detail": "Verifier bounds check violation: data + len > data_end"
            })
            continue

        src_ip = ip.get("src_ip", "")
        dst_ip = ip.get("dst_ip", "")
        proto = ip.get("proto", "")

        # 2. Blacklist check: Line-rate DDoS drop without sk_buff allocation
        if src_ip in blacklist:
            action = "XDP_DROP"
            action_counts[action] += 1
            packet_results.append({
                "pkt_id": p_id,
                "action": action,
                "detail": f"Source IP {src_ip} dropped by eBPF DDoS blacklist map"
            })
            continue

        # 3. AF_XDP Socket check: Zero-copy kernel bypass redirect
        dst_port = l4.get("dst_port") if l4 else None
        if dst_port and (dst_port in xskmap):
            action = "XDP_REDIRECT"
            action_counts[action] += 1
            packet_results.append({
                "pkt_id": p_id,
                "action": action,
                "redirect_target": "AF_XDP_UMEM",
                "target_port": dst_port,
                "detail": f"Zero-copy kernel bypass redirect to AF_XDP socket on port {dst_port}"
            })
            continue

        # 4. Devmap forwarding check: L2/L3 rewrite and inter-interface redirect
        if dst_ip in devmap:
            tgt_if = devmap[dst_ip]
            action = "XDP_REDIRECT"
            action_counts[action] += 1
            new_ttl = ip.get("ttl", 64) - 1
            out_mac = interfaces.get(tgt_if, {}).get("mac", "00:00:00:00:00:00")
            packet_results.append({
                "pkt_id": p_id,
                "action": action,
                "redirect_target": "DEVMAP",
                "target_ifindex": tgt_if,
                "modified_headers": {
                    "new_src_mac": out_mac,
                    "new_ttl": new_ttl
                },
                "detail": f"L2/L3 header rewritten and redirected to ifindex {tgt_if}"
            })
            continue

        # 5. Hairpin TX Bounce: Echo bounce back to ingress interface
        if proto == "ICMP":
            action = "XDP_TX"
            action_counts[action] += 1
            packet_results.append({
                "pkt_id": p_id,
                "action": action,
                "tx_ifindex": rx_if,
                "swapped_headers": {
                    "src_mac": eth.get("dst_mac"),
                    "dst_mac": eth.get("src_mac"),
                    "src_ip": dst_ip,
                    "dst_ip": src_ip
                },
                "detail": f"ICMP echo hairpinned directly back to TX ring on ifindex {rx_if}"
            })
            continue

        # 6. CPUMAP distribution: RSS multicore rebalancing
        if cpumap_enabled:
            sport = l4.get("src_port", 0) if l4 else 0
            dport = l4.get("dst_port", 0) if l4 else 0
            hash_str = f"{src_ip}-{dst_ip}-{proto}-{sport}-{dport}"
            target_cpu = sum(ord(c) for c in hash_str) % cpu_cores
            if target_cpu != rx_cpu:
                action = "XDP_REDIRECT"
                action_counts[action] += 1
                packet_results.append({
                    "pkt_id": p_id,
                    "action": action,
                    "redirect_target": "CPUMAP",
                    "target_cpu": target_cpu,
                    "detail": f"Load re-distributed from CPU {rx_cpu} to CPU {target_cpu} via cpumap"
                })
                continue

        # 7. Default PASS: Pass to Linux network stack (sk_buff allocated)
        action = "XDP_PASS"
        action_counts[action] += 1
        packet_results.append({
            "pkt_id": p_id,
            "action": action,
            "detail": "Packet passed up to kernel network stack (sk_buff allocated)"
        })

    total_pkts = len(packets)
    efficiency = round(
        (action_counts["XDP_DROP"] + action_counts["XDP_TX"] + action_counts["XDP_REDIRECT"]) / total_pkts, 4
    ) if total_pkts else 0.0

    return {
        "summary": {
            "total_packets_processed": total_pkts,
            "verdict_counts": action_counts,
            "line_rate_efficiency": efficiency
        },
        "packets": packet_results
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_xdp_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
