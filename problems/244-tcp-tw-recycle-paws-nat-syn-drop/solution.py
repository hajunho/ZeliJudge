import sys
import json
from collections import deque
from typing import Dict, List, Any

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    server_config = input_data.get("server_config", {})
    tcp_ts = server_config.get("tcp_timestamps", 1)
    tcp_tw_recycle = server_config.get("tcp_tw_recycle", 0)
    tcp_tw_reuse = server_config.get("tcp_tw_reuse", 0)
    tw_timeout_sec = server_config.get("time_wait_timeout_sec", 60)
    recycle_timeout_sec = server_config.get("recycle_timeout_sec", 3)

    events = input_data.get("events", [])

    peer_cache = {}
    sockets = {}
    tw_queue = deque()

    total_syn = 0
    established = 0
    syn_dropped_paws = 0
    retrans_count = 0
    recycled_count = 0
    max_conn_latency_ms = 0

    pending_syns = {}

    for ev in events:
        time_ms = ev.get("time_ms", 0)
        ev_type = ev.get("type")
        conn_id = ev.get("conn_id")

        while tw_queue and time_ms >= tw_queue[0][0]:
            exp_time, cid = tw_queue.popleft()
            if cid in sockets and sockets[cid]["state"] == "TIME_WAIT":
                sockets[cid]["state"] = "CLOSED"
                recycled_count += 1

        if ev_type == "SYN_PACKET":
            total_syn += 1
            client_ip = ev.get("client_ip")
            client_port = ev.get("client_port")
            ts_val = ev.get("ts_val", 0)
            is_retrans = ev.get("is_retransmission", False)
            if is_retrans:
                retrans_count += 1

            if conn_id not in pending_syns:
                pending_syns[conn_id] = time_ms

            drop = False
            if tcp_ts == 1 and tcp_tw_recycle == 1:
                if client_ip in peer_cache:
                    peer = peer_cache[client_ip]
                    if (time_ms - peer["last_seen_time_ms"]) <= 60000:
                        if ts_val < peer["last_ts_val"]:
                            drop = True

            if drop:
                syn_dropped_paws += 1
                continue
            else:
                if tcp_ts == 1 and tcp_tw_recycle == 1:
                    peer_cache[client_ip] = {
                        "last_ts_val": ts_val,
                        "last_seen_time_ms": time_ms
                    }
                sockets[conn_id] = {
                    "conn_id": conn_id,
                    "client_ip": client_ip,
                    "client_port": client_port,
                    "state": "SYN_RCVD",
                    "start_time_ms": pending_syns.get(conn_id, time_ms)
                }

        elif ev_type == "CONNECTION_ESTABLISHED":
            if conn_id in sockets and sockets[conn_id]["state"] in ("SYN_RCVD", "ESTABLISHED"):
                sockets[conn_id]["state"] = "ESTABLISHED"
                established += 1
                start_t = pending_syns.get(conn_id, time_ms)
                lat = time_ms - start_t
                if lat > max_conn_latency_ms:
                    max_conn_latency_ms = lat

        elif ev_type == "CONNECTION_CLOSE":
            if conn_id in sockets:
                s = sockets[conn_id]
                initiator = ev.get("initiator", "SERVER")
                if initiator == "SERVER":
                    timeout = recycle_timeout_sec if tcp_tw_recycle == 1 else tw_timeout_sec
                    s["state"] = "TIME_WAIT"
                    s["tw_expire_ms"] = time_ms + (timeout * 1000)
                    tw_queue.append((s["tw_expire_ms"], conn_id))
                else:
                    s["state"] = "CLOSED"

    while tw_queue and events and events[-1].get("time_ms", 0) >= tw_queue[0][0]:
        exp_time, cid = tw_queue.popleft()
        if cid in sockets and sockets[cid]["state"] == "TIME_WAIT":
            sockets[cid]["state"] = "CLOSED"
            recycled_count += 1

    active_tw = len([s for s in sockets.values() if s["state"] == "TIME_WAIT"])

    anomalies = []
    if syn_dropped_paws > 0:
        anomalies.append("TCP_TW_RECYCLE_NAT_PAWS_SYN_DROP")

    if retrans_count >= 3 or max_conn_latency_ms >= 3000:
        anomalies.append("INTERMITTENT_CLIENT_CONNECTIVITY_TIMEOUT")

    if active_tw >= 5000 and tcp_tw_reuse == 0:
        anomalies.append("TIME_WAIT_SOCKET_EXHAUSTION_RISK")

    recommendations = []
    if "TCP_TW_RECYCLE_NAT_PAWS_SYN_DROP" in anomalies:
        recommendations.append("DISABLE_TCP_TW_RECYCLE_IMMEDIATELY")
        recommendations.append("UPGRADE_KERNEL_VERSION_4_12_PLUS")
    if tcp_tw_reuse == 0 and active_tw > 1000:
        recommendations.append("ENABLE_TCP_TW_REUSE_FOR_OUTBOUND_CLIENTS")

    diag_parts = []
    if "TCP_TW_RECYCLE_NAT_PAWS_SYN_DROP" in anomalies:
        diag_parts.append(f"동일 NAT IP 뒤의 복수 클라이언트 간 타임스탬프 불일치로 인해 서버가 SYN 패킷 {syn_dropped_paws}건을 사일런트 드롭함 (PAWS 거부).")
    if "INTERMITTENT_CLIENT_CONNECTIVITY_TIMEOUT" in anomalies:
        diag_parts.append(f"SYN 드롭으로 인한 재전송 타임아웃({retrans_count}회) 및 연결 지연시간({max_conn_latency_ms}ms) 발생.")
    if "TIME_WAIT_SOCKET_EXHAUSTION_RISK" in anomalies:
        diag_parts.append(f"TIME_WAIT 소켓 누적({active_tw}개)으로 인한 로컬 포트 고갈 위험.")
    if not anomalies:
        if tcp_tw_recycle == 0:
            diag_parts.append("tcp_tw_recycle가 안전하게 비활성화되어 NAT 환경에서도 모든 클라이언트의 SYN이 정상 수락되었습니다.")
        else:
            diag_parts.append("단일 클라이언트 환경에서 타임스탬프 순서가 정상 유지되어 연결이 안정적으로 수립되었습니다.")

    diagnosis = " ".join(diag_parts)

    return {
        "server_config": {
            "tcp_timestamps": tcp_ts,
            "tcp_tw_recycle": tcp_tw_recycle,
            "tcp_tw_reuse": tcp_tw_reuse
        },
        "total_syn_packets": total_syn,
        "established_connections": established,
        "syn_dropped_paws": syn_dropped_paws,
        "retransmitted_syn_count": retrans_count,
        "active_time_wait_sockets": active_tw,
        "recycled_time_wait_sockets": recycled_count,
        "max_connection_latency_ms": max_conn_latency_ms,
        "anomalies": anomalies,
        "recommendations": recommendations,
        "diagnosis": diagnosis
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
