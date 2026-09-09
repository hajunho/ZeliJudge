#!/usr/bin/env python3
"""
ZeliJudge Problem #205: 쿠버네티스 CNI 네트워크: veth MTU 불일치, PMTU Discovery 블랙홀과 iptables TCP MSS Clamping
Solution Implementation
"""
import sys
import json

def simulate(input_data):
    cfg = input_data.get("network_config", {})
    pod_veth_mtu = cfg.get("pod_veth_mtu", 1500)
    tunnel_overhead_bytes = cfg.get("tunnel_overhead_bytes", 50)
    underlay_physical_mtu = cfg.get("underlay_physical_mtu", 1500)
    icmp_blocked = cfg.get("icmp_fragmentation_needed_blocked", True)
    tcp_mss_clamping = cfg.get("tcp_mss_clamping_enabled", False)
    clamped_mss_target = cfg.get("clamped_mss_target", None)

    effective_path_mtu = underlay_physical_mtu - tunnel_overhead_bytes

    connections = input_data.get("tcp_connections", [])

    total_connections = len(connections)
    total_packets_sent = 0
    packets_delivered_line_rate = 0
    packets_dropped_mtu_exceeded = 0
    icmp_frag_needed_sent = 0
    icmp_frag_needed_delivered = 0
    pmtu_blackhole_hangs_detected = 0
    effective_mss_negotiated = 0

    IP_TCP_HEADER_SIZE = 40

    for conn in connections:
        conn_id = conn.get("connection_id", "conn_0")
        client_mss = conn.get("client_advertised_mss", pod_veth_mtu - IP_TCP_HEADER_SIZE)
        packets = conn.get("packets", [])

        negotiated_mss = client_mss
        if tcp_mss_clamping:
            if clamped_mss_target is not None:
                negotiated_mss = min(negotiated_mss, clamped_mss_target)
            else:
                auto_clamp = effective_path_mtu - IP_TCP_HEADER_SIZE
                negotiated_mss = min(negotiated_mss, auto_clamp)

        effective_mss_negotiated = negotiated_mss
        conn_blackholed = False

        for pkt in packets:
            total_packets_sent += 1
            pkt_type = pkt.get("type", "DATA")
            payload = pkt.get("payload_bytes", 0)
            df_bit = pkt.get("df_bit", True)

            wire_packet_size = payload + IP_TCP_HEADER_SIZE
            if pkt_type == "SYN":
                wire_packet_size = 60

            if wire_packet_size <= effective_path_mtu:
                packets_delivered_line_rate += 1
            else:
                if df_bit:
                    packets_dropped_mtu_exceeded += 1
                    icmp_frag_needed_sent += 1
                    if not icmp_blocked:
                        icmp_frag_needed_delivered += 1
                        negotiated_mss = effective_path_mtu - IP_TCP_HEADER_SIZE
                    else:
                        conn_blackholed = True
                else:
                    packets_delivered_line_rate += 1

        if conn_blackholed:
            pmtu_blackhole_hangs_detected += 1

    if pmtu_blackhole_hangs_detected > 0:
        status = "PMTU_BLACKHOLE_PACKET_DROP"
    elif not tcp_mss_clamping and pod_veth_mtu > effective_path_mtu and packets_dropped_mtu_exceeded > 0 and icmp_blocked:
        status = "PMTU_BLACKHOLE_PACKET_DROP"
    elif not tcp_mss_clamping and any(not p.get("df_bit", True) and p.get("payload_bytes", 0) + IP_TCP_HEADER_SIZE > effective_path_mtu for c in connections for p in c.get("packets", [])):
        status = "IP_FRAGMENTATION_OVERHEAD_COLLAPSE"
    else:
        status = "OPTIMAL_TCP_MSS_CLAMPING_PMTU_TUNED"

    root_causes = {
        "PMTU_BLACKHOLE_PACKET_DROP": (
            f"쿠버네티스 CNI PMTU 블랙홀 패킷 폐기 참사: 파드 veth MTU({pod_veth_mtu})가 오버레이 터널 유효 MTU({effective_path_mtu})보다 커서 "
            f"DF=1 대형 패킷 {packets_dropped_mtu_exceeded}건이 게이트웨이에서 폐기되었으나, "
            "방화벽의 ICMP Type 3 Code 4 차단으로 오류 메시지가 유실되어 연결이 영구 타임아웃(Blackhole Hang)에 빠짐."
        ),
        "IP_FRAGMENTATION_OVERHEAD_COLLAPSE": (
            f"IP 단편화(Fragmentation) 성능 저하 참사: TCP MSS Clamping 부재로 오버레이 터널 경계에서 "
            f"패킷이 강제 조각화(Fragmentation)되어 네트워크 처리량 저하 및 패킷 재전송 오버헤드 발생."
        ),
        "OPTIMAL_TCP_MSS_CLAMPING_PMTU_TUNED": (
            f"쿠버네티스 CNI TCP MSS Clamping 최적화 완수: iptables mangle 테이블에서 SYN 패킷의 MSS를 "
            f"{effective_mss_negotiated}B(유효 경로 MTU {effective_path_mtu}B - 헤더 40B)로 강제 정합하여, "
            f"ICMP 차단 환경에서도 패킷 드롭 0건 및 100% 무손실 고속 통신 달성."
        )
    }

    return {
        "status": status,
        "metrics": {
            "total_connections": total_connections,
            "total_packets_sent": total_packets_sent,
            "packets_delivered_line_rate": packets_delivered_line_rate,
            "packets_dropped_mtu_exceeded": packets_dropped_mtu_exceeded,
            "icmp_frag_needed_sent": icmp_frag_needed_sent,
            "icmp_frag_needed_delivered": icmp_frag_needed_delivered,
            "pmtu_blackhole_hangs_detected": pmtu_blackhole_hangs_detected,
            "effective_mss_negotiated": effective_mss_negotiated
        },
        "root_cause_analysis": root_causes.get(status, "")
    }

def main():
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            return
        input_data = json.loads(raw_input)
        result = simulate(input_data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
