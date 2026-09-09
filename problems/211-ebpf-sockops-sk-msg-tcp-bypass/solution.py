#!/usr/bin/env python3
"""
ZeliJudge Problem #211: Linux eBPF sockops & sk_msg - Bypassing TCP/IP Stack for Local Pod-to-Pod Communication vs iptables & conntrack Overhead
리눅스 커널 eBPF sockops와 sk_msg: 로컬 컨테이너 간 TCP/IP 네트워크 스택 완전 바이패스와 소켓 직접 리다이렉션

Reference Implementation
"""

import sys
import json
from typing import Dict, Any, List

def simulate_sockops(data: Dict[str, Any]) -> Dict[str, Any]:
    net_cfg = data["network_config"]
    local_node = net_cfg.get("node_id", "worker-node-1")
    conntrack_max = net_cfg.get("conntrack_table_max", 65536)
    iptables_rules = net_cfg.get("iptables_rules_count", 500)
    mode = net_cfg.get("mode", "EBPF_SOCKOPS_SK_MSG_BYPASS")

    legacy_lat_us = net_cfg.get("base_costs", {}).get("legacy_tcp_ip_stack_latency_us", 25.0)
    ebpf_lat_us = net_cfg.get("base_costs", {}).get("ebpf_sockops_redirect_latency_us", 4.2)
    iptables_penalty_per_100 = net_cfg.get("base_costs", {}).get("iptables_traversal_penalty_per_100_rules_us", 1.5)
    conntrack_penalty_us = net_cfg.get("base_costs", {}).get("conntrack_lookup_penalty_us", 0.8)

    endpoints = {}
    for ep in data.get("endpoints", []):
        endpoints[ep["ip"]] = ep["node"]

    total_messages = 0
    local_traffic_count = 0
    remote_traffic_count = 0
    ebpf_redirected_count = 0
    conntrack_entries_created = 0
    conntrack_overflow = False
    total_latency_us = 0.0
    dropped_packets = 0

    legacy_overhead_us = (iptables_rules / 100.0) * iptables_penalty_per_100 + conntrack_penalty_us
    full_legacy_latency = legacy_lat_us + legacy_overhead_us

    for req in data.get("workload", []):
        src_ip = req.get("src_ip", "")
        dst_ip = req.get("dst_ip", "")
        count = int(req.get("count", 1))
        is_new_conn = req.get("is_new_connection", True)

        src_node = endpoints.get(src_ip, local_node)
        dst_node = endpoints.get(dst_ip, "")

        is_local_comm = (src_node == local_node and dst_node == local_node)

        for _ in range(count):
            total_messages += 1
            if is_local_comm:
                local_traffic_count += 1
                if mode == "EBPF_SOCKOPS_SK_MSG_BYPASS":
                    ebpf_redirected_count += 1
                    total_latency_us += ebpf_lat_us
                else:
                    if is_new_conn:
                        conntrack_entries_created += 1
                        if conntrack_entries_created > conntrack_max:
                            conntrack_overflow = True
                            dropped_packets += 1
                            continue

                    total_latency_us += full_legacy_latency
            else:
                remote_traffic_count += 1
                if is_new_conn:
                    conntrack_entries_created += 1
                    if conntrack_entries_created > conntrack_max:
                        conntrack_overflow = True
                        dropped_packets += 1
                        continue
                total_latency_us += full_legacy_latency + 15.0

    successful_messages = total_messages - dropped_packets
    avg_latency = round(total_latency_us / successful_messages, 2) if successful_messages > 0 else 0.0
    bypassed_pct = round((ebpf_redirected_count / local_traffic_count * 100.0), 2) if local_traffic_count > 0 else 0.0

    if conntrack_overflow:
        verdict = "CONNTRACK_TABLE_EXHAUSTION_PACKET_DROP"
    elif mode == "EBPF_SOCKOPS_SK_MSG_BYPASS":
        verdict = "OPTIMAL_EBPF_SOCKOPS_STACK_BYPASS"
    else:
        verdict = "LEGACY_STACK_IPTABLES_OVERHEAD"

    output = {
        "status": "SUCCESS" if not conntrack_overflow else "FAILED",
        "verdict": verdict,
        "mode": mode,
        "metrics": {
            "total_messages": total_messages,
            "successful_messages": successful_messages,
            "dropped_packets": dropped_packets,
            "local_traffic_count": local_traffic_count,
            "remote_traffic_count": remote_traffic_count,
            "ebpf_redirected_count": ebpf_redirected_count,
            "tcp_ip_stack_bypassed_pct": bypassed_pct,
            "conntrack_entries_created": conntrack_entries_created,
            "conntrack_table_overflow": conntrack_overflow,
            "average_latency_us": avg_latency
        }
    }
    return output

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_sockops(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
